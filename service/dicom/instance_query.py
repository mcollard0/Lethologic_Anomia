"""
DICOM Instance-to-Instance Query Service

Enables two Lethologica instances to discover and query each other's DICOM data.
Implements distributed DICOM discovery and federated query capabilities.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
import socket
import ipaddress

from pynetdicom import AE
from pynetdicom.sop_class import Verification, StudyRootQueryRetrieveInformationModelFind

from core.custom_logging import get_logger
from core.database import DatabaseManager
from core.config import Settings
from .discovery import DICOMDiscoveryService
from core.ssl_manager import SSLManager as DICOMSSLManager

logger = get_logger(__name__)


class DICOMInstanceQueryService:
    """
    Service for managing queries between multiple Lethologica instances
    
    Provides capabilities for:
    - Auto-discovery of peer Lethologica instances on the network
    - Cross-instance DICOM queries with federation
    - Distributed study availability tracking
    - Load balancing across instances
    - Secure encrypted connections between instances
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize instance query service
        
        Args:
            db_manager: Database manager instance
            settings: Application settings
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # Configuration
        self.config = {
            'ae_title': 'LETHOLOGIC_FEDERATED',
            'local_port': 11118,  # Default port for federation
            'discovery_interval': 300,  # 5 minutes
            'query_timeout': 60,
            'max_concurrent_queries': 10,
            'federation_networks': ['192.168.0.0/16', '10.0.0.0/8', '172.16.0.0/12'],
            'instance_ports': [11112, 11114, 11116, 11118],  # Common DICOM ports
            'ssl_enabled': False  # Will be set based on SSL manager availability
        }
        
        # Service instances
        self.discovery_service = DICOMDiscoveryService(db_manager, settings)
        self.ssl_manager = DICOMSSLManager()
        
        # Runtime state
        self.peer_instances = {}  # Discovered peer instances
        self.federation_ae: Optional[AE] = None
        self.discovery_task: Optional[asyncio.Task] = None
        self.is_running = False
        
        # Initialize AE
        self._initialize_federation_ae()
        
        logger.info("DICOM Instance Query Service initialized")
    
    def _initialize_federation_ae(self):
        """Initialize Application Entity for federation"""
        self.federation_ae = AE(ae_title=self.config['ae_title'])
        self.federation_ae.add_requested_context(Verification)
        self.federation_ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        self.federation_ae.network_timeout = self.config['query_timeout']
        
        # Check SSL availability
        if self.ssl_manager.validate_key_pair():
            self.config['ssl_enabled'] = True
            logger.info("SSL certificates available - federation will use secure connections")
        else:
            logger.info("SSL certificates not available - federation will use plain connections")
    
    async def start_federation_service(self):
        """Start the federation service with peer discovery"""
        if self.is_running:
            logger.warning("Federation service already running")
            return
        
        logger.info("Starting DICOM Instance Query Federation Service")
        
        try:
            # Ensure database tables exist
            await self._ensure_federation_tables()
            
            # Start discovery task
            self.discovery_task = asyncio.create_task(self._continuous_peer_discovery())
            
            self.is_running = True
            logger.info(f"Federation service started on port {self.config['local_port']}")
            
        except Exception as e:
            logger.error(f"Failed to start federation service: {e}")
            raise
    
    async def stop_federation_service(self):
        """Stop the federation service"""
        if not self.is_running:
            return
        
        logger.info("Stopping DICOM Instance Query Federation Service")
        
        # Cancel discovery task
        if self.discovery_task:
            self.discovery_task.cancel()
            try:
                await self.discovery_task
            except asyncio.CancelledError:
                pass
        
        self.is_running = False
        logger.info("Federation service stopped")
    
    async def _continuous_peer_discovery(self):
        """Continuously discover peer Lethologica instances"""
        while self.is_running:
            try:
                await self.discover_peer_instances()
                
                # Wait for next discovery cycle
                await asyncio.sleep(self.config['discovery_interval'])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in peer discovery: {e}")
                await asyncio.sleep(60)  # Wait before retrying
    
    async def discover_peer_instances(self) -> Dict[str, Any]:
        """
        Discover peer Lethologica instances on configured networks
        
        Returns:
            Dictionary with discovery results
        """
        logger.info("Starting peer instance discovery")
        
        discovery_result = {
            'discovered_instances': 0,
            'total_networks_scanned': 0,
            'new_instances': 0,
            'updated_instances': 0,
            'discovery_time': datetime.now().isoformat(),
            'instances': {}
        }
        
        try:
            for network in self.config['federation_networks']:
                logger.info(f"Scanning network: {network}")
                
                # Discover DICOM services in the network
                discovered_services = await self.discovery_service.discover_network_range(
                    network=network,
                    ports=self.config['instance_ports']
                )
                
                discovery_result['total_networks_scanned'] += 1
                
                # Process discovered services to identify Lethologica instances
                for service in discovered_services:
                    instance_info = await self._identify_lethologic_instance(service)
                    
                    if instance_info:
                        instance_key = f"{service['ip_address']}:{service['port']}"
                        
                        # Check if this is a new instance
                        if instance_key not in self.peer_instances:
                            discovery_result['new_instances'] += 1
                            logger.info(f"Discovered new Lethologica instance: {instance_key}")
                        else:
                            discovery_result['updated_instances'] += 1
                        
                        self.peer_instances[instance_key] = instance_info
                        discovery_result['instances'][instance_key] = instance_info
                        discovery_result['discovered_instances'] += 1
            
            # Store discovery results
            await self._store_peer_discovery_result(discovery_result)
            
            logger.info(f"Peer discovery completed: {discovery_result['discovered_instances']} instances found")
            return discovery_result
            
        except Exception as e:
            logger.error(f"Error during peer discovery: {e}")
            discovery_result['error'] = str(e)
            return discovery_result
    
    async def _identify_lethologic_instance(self, service: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Identify if a discovered service is a Lethologica instance
        
        Args:
            service: Discovered DICOM service info
            
        Returns:
            Instance information if it's a Lethologica instance, None otherwise
        """
        try:
            # Check if the AE title suggests it's a Lethologica instance
            ae_title = service.get('ae_title', '').upper()
            lethologic_patterns = ['LETHOLOGIC', 'MIGRATION_SCP', 'ANOMIA', 'FEDERATED']
            
            is_lethologic = any(pattern in ae_title for pattern in lethologic_patterns)
            
            if is_lethologic:
                # Perform additional verification - try to query capabilities
                capabilities = await self._query_instance_capabilities(
                    service['ip_address'], 
                    service['port'], 
                    service['ae_title']
                )
                
                if capabilities:
                    instance_info = {
                        'ip_address': service['ip_address'],
                        'port': service['port'],
                        'ae_title': service['ae_title'],
                        'last_seen': datetime.now().isoformat(),
                        'capabilities': capabilities,
                        'is_lethologic': True,
                        'federation_compatible': True,
                        'ssl_support': False,  # Will be determined by capability query
                        'study_count_estimate': capabilities.get('estimated_studies', 0)
                    }
                    
                    return instance_info
            
            return None
            
        except Exception as e:
            logger.debug(f"Error identifying instance {service.get('ip_address')}:{service.get('port')}: {e}")
            return None
    
    async def _query_instance_capabilities(
        self, 
        host: str, 
        port: int, 
        ae_title: str
    ) -> Optional[Dict[str, Any]]:
        """
        Query an instance for its capabilities and metadata
        
        Args:
            host: Instance IP address
            port: Instance port
            ae_title: Instance AE title
            
        Returns:
            Capabilities dictionary if successful, None otherwise
        """
        try:
            # Use discovery service to perform time-based query to estimate study count
            discovery_result = await self.discovery_service.discover_by_time_range(
                host=host,
                port=port, 
                ae_title=ae_title,
                hours_back=24*7,  # Check last week
                auto_backoff=True
            )
            
            if 'error' not in discovery_result:
                capabilities = {
                    'query_support': True,
                    'estimated_studies': discovery_result.get('total_studies', 0),
                    'estimated_series': discovery_result.get('total_series', 0),
                    'backoff_capable': discovery_result.get('backoff_triggered', False),
                    'last_capability_check': datetime.now().isoformat(),
                    'response_time': sum(q.get('query_duration', 0) for q in discovery_result.get('queries', [])),
                    'queries_supported': len(discovery_result.get('queries', [])) > 0
                }
                
                return capabilities
            
            return None
            
        except Exception as e:
            logger.debug(f"Error querying capabilities for {host}:{port}: {e}")
            return None
    
    async def federated_study_query(
        self, 
        query_params: Dict[str, Any],
        target_instances: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Perform a federated study query across multiple instances
        
        Args:
            query_params: DICOM query parameters
            target_instances: List of instance keys to query (None = query all)
            
        Returns:
            Aggregated query results from all instances
        """
        logger.info(f"Starting federated query with params: {query_params}")
        
        # Determine target instances
        if target_instances is None:
            target_instances = list(self.peer_instances.keys())
        
        # Validate target instances
        valid_targets = [key for key in target_instances if key in self.peer_instances]
        
        if not valid_targets:
            return {
                'error': 'No valid target instances found',
                'total_instances_queried': 0,
                'total_studies_found': 0,
                'results': []
            }
        
        federated_result = {
            'query_params': query_params,
            'target_instances': valid_targets,
            'total_instances_queried': 0,
            'successful_queries': 0,
            'failed_queries': 0,
            'total_studies_found': 0,
            'total_series_found': 0,
            'query_start_time': datetime.now().isoformat(),
            'results': [],
            'instance_results': {}
        }
        
        # Create concurrent query tasks
        query_tasks = []
        semaphore = asyncio.Semaphore(self.config['max_concurrent_queries'])
        
        async def query_instance(instance_key: str):
            async with semaphore:
                return await self._query_single_instance(instance_key, query_params)
        
        # Launch all queries concurrently
        for instance_key in valid_targets:
            task = asyncio.create_task(query_instance(instance_key))
            query_tasks.append((instance_key, task))
        
        # Gather results
        for instance_key, task in query_tasks:
            try:
                instance_result = await task
                
                federated_result['total_instances_queried'] += 1
                federated_result['instance_results'][instance_key] = instance_result
                
                if instance_result.get('success', False):
                    federated_result['successful_queries'] += 1
                    federated_result['total_studies_found'] += instance_result.get('study_count', 0)
                    federated_result['total_series_found'] += instance_result.get('series_count', 0)
                    
                    # Add instance-specific results to global results
                    for study in instance_result.get('studies', []):
                        study['source_instance'] = instance_key
                        federated_result['results'].append(study)
                else:
                    federated_result['failed_queries'] += 1
                    
            except Exception as e:
                logger.error(f"Error querying instance {instance_key}: {e}")
                federated_result['failed_queries'] += 1
                federated_result['instance_results'][instance_key] = {
                    'success': False,
                    'error': str(e)
                }
        
        federated_result['query_end_time'] = datetime.now().isoformat()
        
        # Store federated query results
        await self._store_federated_query_result(federated_result)
        
        logger.info(f"Federated query completed: {federated_result['total_studies_found']} studies from {federated_result['successful_queries']} instances")
        
        return federated_result
    
    async def _query_single_instance(
        self, 
        instance_key: str, 
        query_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Query a single instance with the given parameters
        
        Args:
            instance_key: Instance identifier (host:port)
            query_params: DICOM query parameters
            
        Returns:
            Query results for the instance
        """
        instance_info = self.peer_instances.get(instance_key)
        if not instance_info:
            return {'success': False, 'error': 'Instance not found'}
        
        try:
            # Extract time range if specified
            hours_back = query_params.get('hours_back', 24)
            
            # Use discovery service for time-based queries
            if 'time_range' in query_params or hours_back:
                result = await self.discovery_service.discover_by_time_range(
                    host=instance_info['ip_address'],
                    port=instance_info['port'],
                    ae_title=instance_info['ae_title'],
                    hours_back=hours_back,
                    auto_backoff=True
                )
                
                if 'error' not in result:
                    return {
                        'success': True,
                        'study_count': result.get('total_studies', 0),
                        'series_count': result.get('total_series', 0),
                        'query_duration': sum(q.get('query_duration', 0) for q in result.get('queries', [])),
                        'studies': [],  # Would need to parse from detailed query results
                        'instance_info': instance_info
                    }
                else:
                    return {
                        'success': False,
                        'error': result.get('error'),
                        'instance_info': instance_info
                    }
            else:
                # Perform standard DICOM query (not implemented in this example)
                return {
                    'success': False,
                    'error': 'Standard DICOM queries not yet implemented',
                    'instance_info': instance_info
                }
                
        except Exception as e:
            logger.error(f"Error querying instance {instance_key}: {e}")
            return {
                'success': False,
                'error': str(e),
                'instance_info': instance_info
            }
    
    async def get_federation_status(self) -> Dict[str, Any]:
        """
        Get current federation status and statistics
        
        Returns:
            Federation status information
        """
        status = {
            'is_running': self.is_running,
            'local_port': self.config['local_port'],
            'ssl_enabled': self.config['ssl_enabled'],
            'peer_instances': len(self.peer_instances),
            'discovery_networks': self.config['federation_networks'],
            'last_discovery': None,
            'instance_details': {},
            'capabilities': {
                'federated_queries': True,
                'concurrent_queries': self.config['max_concurrent_queries'],
                'ssl_support': self.config['ssl_enabled'],
                'time_based_discovery': True,
                'auto_peer_discovery': True
            }
        }
        
        # Add peer instance details
        for instance_key, instance_info in self.peer_instances.items():
            status['instance_details'][instance_key] = {
                'ae_title': instance_info.get('ae_title'),
                'last_seen': instance_info.get('last_seen'),
                'estimated_studies': instance_info.get('capabilities', {}).get('estimated_studies', 0),
                'federation_compatible': instance_info.get('federation_compatible', False)
            }
        
        # Get last discovery time from database
        try:
            query = "SELECT MAX(discovery_time) as last_discovery FROM dicom_peer_discovery_results"
            result = await self.db_manager.execute_query(query)
            if result and result[0]['last_discovery']:
                status['last_discovery'] = result[0]['last_discovery']
        except Exception as e:
            logger.debug(f"Error getting last discovery time: {e}")
        
        return status
    
    async def query_specific_instances(
        self, 
        instance_keys: List[str], 
        hours_back: int = 24
    ) -> Dict[str, Any]:
        """
        Query specific instances by their keys
        
        Args:
            instance_keys: List of instance identifiers
            hours_back: Hours to look back for studies
            
        Returns:
            Query results from specified instances
        """
        query_params = {
            'hours_back': hours_back,
            'time_range': True
        }
        
        return await self.federated_study_query(
            query_params=query_params,
            target_instances=instance_keys
        )
    
    async def _store_peer_discovery_result(self, result: Dict[str, Any]):
        """Store peer discovery results in database"""
        try:
            await self._ensure_federation_tables()
            
            query = """
                INSERT INTO dicom_peer_discovery_results (
                    discovery_time, discovered_instances, total_networks_scanned,
                    new_instances, updated_instances, result_data
                ) VALUES (?, ?, ?, ?, ?, ?)
            """
            
            values = (
                result['discovery_time'],
                result['discovered_instances'],
                result['total_networks_scanned'],
                result['new_instances'],
                result['updated_instances'],
                json.dumps(result)
            )
            
            await self.db_manager.execute_query(query, values)
            
            # Update peer instances table
            for instance_key, instance_info in result.get('instances', {}).items():
                await self._store_peer_instance_info(instance_key, instance_info)
            
        except Exception as e:
            logger.error(f"Error storing peer discovery result: {e}")
    
    async def _store_peer_instance_info(self, instance_key: str, instance_info: Dict[str, Any]):
        """Store or update peer instance information"""
        try:
            host, port = instance_key.split(':')
            
            query = """
                INSERT OR REPLACE INTO dicom_peer_instances (
                    instance_key, ip_address, port, ae_title, last_seen,
                    is_lethologic, federation_compatible, ssl_support,
                    estimated_studies, capabilities_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            values = (
                instance_key,
                host,
                int(port),
                instance_info.get('ae_title', ''),
                instance_info.get('last_seen'),
                instance_info.get('is_lethologic', False),
                instance_info.get('federation_compatible', False),
                instance_info.get('ssl_support', False),
                instance_info.get('study_count_estimate', 0),
                json.dumps(instance_info.get('capabilities', {}))
            )
            
            await self.db_manager.execute_query(query, values)
            
        except Exception as e:
            logger.error(f"Error storing peer instance info: {e}")
    
    async def _store_federated_query_result(self, result: Dict[str, Any]):
        """Store federated query results in database"""
        try:
            await self._ensure_federation_tables()
            
            query = """
                INSERT INTO dicom_federated_query_results (
                    query_start_time, query_params, target_instances,
                    total_instances_queried, successful_queries, failed_queries,
                    total_studies_found, total_series_found, result_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            values = (
                result['query_start_time'],
                json.dumps(result['query_params']),
                json.dumps(result['target_instances']),
                result['total_instances_queried'],
                result['successful_queries'],
                result['failed_queries'],
                result['total_studies_found'],
                result['total_series_found'],
                json.dumps(result)
            )
            
            await self.db_manager.execute_query(query, values)
            
        except Exception as e:
            logger.error(f"Error storing federated query result: {e}")
    
    async def _ensure_federation_tables(self):
        """Ensure federation database tables exist"""
        
        # Peer instances table
        peer_instances_query = """
            CREATE TABLE IF NOT EXISTS dicom_peer_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_key TEXT UNIQUE NOT NULL,
                ip_address TEXT NOT NULL,
                port INTEGER NOT NULL,
                ae_title TEXT,
                last_seen TEXT,
                is_lethologic BOOLEAN DEFAULT FALSE,
                federation_compatible BOOLEAN DEFAULT FALSE,
                ssl_support BOOLEAN DEFAULT FALSE,
                estimated_studies INTEGER DEFAULT 0,
                capabilities_data TEXT,  -- JSON
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        
        # Peer discovery results table
        discovery_results_query = """
            CREATE TABLE IF NOT EXISTS dicom_peer_discovery_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discovery_time TEXT NOT NULL,
                discovered_instances INTEGER DEFAULT 0,
                total_networks_scanned INTEGER DEFAULT 0,
                new_instances INTEGER DEFAULT 0,
                updated_instances INTEGER DEFAULT 0,
                result_data TEXT,  -- JSON
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        
        # Federated query results table
        federated_query_results_query = """
            CREATE TABLE IF NOT EXISTS dicom_federated_query_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_start_time TEXT NOT NULL,
                query_params TEXT,  -- JSON
                target_instances TEXT,  -- JSON array
                total_instances_queried INTEGER DEFAULT 0,
                successful_queries INTEGER DEFAULT 0,
                failed_queries INTEGER DEFAULT 0,
                total_studies_found INTEGER DEFAULT 0,
                total_series_found INTEGER DEFAULT 0,
                result_data TEXT,  -- JSON
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        
        await self.db_manager.execute_query(peer_instances_query)
        await self.db_manager.execute_query(discovery_results_query)
        await self.db_manager.execute_query(federated_query_results_query)
        
        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_peer_instances_key ON dicom_peer_instances(instance_key)",
            "CREATE INDEX IF NOT EXISTS idx_discovery_time ON dicom_peer_discovery_results(discovery_time)",
            "CREATE INDEX IF NOT EXISTS idx_federated_query_time ON dicom_federated_query_results(query_start_time)"
        ]
        
        for index_query in indexes:
            await self.db_manager.execute_query(index_query)


__all__ = ['DICOMInstanceQueryService']
