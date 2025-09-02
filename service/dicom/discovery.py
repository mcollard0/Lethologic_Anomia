"""
DICOM Discovery Service

Implements DICOM network discovery and verification functionality.
Can discover DICOM services on the network and verify connectivity.
"""

import asyncio
import socket
import threading
import subprocess
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union
import ipaddress
import concurrent.futures

from pynetdicom import AE, debug_logger
from pynetdicom.sop_class import Verification
from pydicom import Dataset

from core.custom_logging import get_logger
from core.database import DatabaseManager
from core.config import Settings

logger = get_logger(__name__)


class DICOMDiscoveryService:
    """
    DICOM Network Discovery Service
    
    Provides functionality to:
    - Discover DICOM services on network ranges
    - Verify DICOM connectivity with C-ECHO
    - Scan for open DICOM ports
    - Store discovered services in database
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize DICOM discovery service
        
        Args:
            db_manager: Database manager instance
            settings: Application settings
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # Configuration
        self.config = {
            'ae_title': 'DISCOVERY_SCU',
            'timeout': 5,
            'port_range': [104, 11112, 2762, 4242, 8080, 8104],
            'max_workers': 50,
            'network_timeout': 10
        }
        
        # Application Entity for verification
        self.ae: Optional[AE] = None
        
        # Discovery results
        self.discovered_services = []
        self.scan_progress = {
            'total_hosts': 0,
            'scanned_hosts': 0,
            'discovered_services': 0,
            'active_scans': 0,
            'start_time': None,
            'end_time': None
        }
        
        # Initialize AE
        self._initialize_ae()
        
        # Time-based discovery configuration
        self.time_discovery_config = {
            'initial_time_range_hours': 24,
            'backoff_ranges': [12, 6, 3, 1, 0.5],  # Hours
            'limit_thresholds': [100, 200, 500, 512, 1000, 1024, 2048],  # Common limits
            'max_attempts': 5
        }
        
        logger.info("DICOM Discovery Service initialized")
    
    def _initialize_ae(self):
        """Initialize Application Entity for discovery"""
        self.ae = AE(ae_title=self.config['ae_title'])
        self.ae.add_requested_context(Verification)
        self.ae.network_timeout = self.config['network_timeout']
        
    async def discover_network_range(
        self, 
        network: str,
        ports: Optional[List[int]] = None,
        ae_title_pattern: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Discover DICOM services in a network range
        
        Args:
            network: Network range in CIDR notation (e.g., "192.168.1.0/24")
            ports: List of ports to scan (default: standard DICOM ports)
            ae_title_pattern: Pattern to match AE titles (optional)
            
        Returns:
            List of discovered DICOM services
        """
        try:
            # Parse network range
            network_obj = ipaddress.ip_network(network, strict=False)
            hosts = list(network_obj.hosts())
            
            # Use default ports if none provided
            if ports is None:
                ports = self.config['port_range']
            
            # Reset progress tracking
            total_combinations = len(hosts) * len(ports)
            self.scan_progress = {
                'total_hosts': len(hosts),
                'scanned_hosts': 0,
                'discovered_services': 0,
                'active_scans': 0,
                'start_time': datetime.now(),
                'end_time': None,
                'total_combinations': total_combinations,
                'scanned_combinations': 0
            }
            
            logger.info(f"Starting network discovery: {network} ({len(hosts)} hosts, {len(ports)} ports)")
            
            # Create list of all host:port combinations
            scan_targets = []
            for host in hosts:
                for port in ports:
                    scan_targets.append((str(host), port))
            
            # Perform concurrent scanning
            discovered = []
            semaphore = asyncio.Semaphore(self.config['max_workers'])
            
            async def scan_target(host_port):
                async with semaphore:
                    host, port = host_port
                    result = await self._scan_host_port(host, port, ae_title_pattern)
                    self.scan_progress['scanned_combinations'] += 1
                    
                    # Update progress every 50 scans
                    if self.scan_progress['scanned_combinations'] % 50 == 0:
                        progress = (self.scan_progress['scanned_combinations'] / total_combinations) * 100
                        logger.info(f"Discovery progress: {progress:.1f}% ({self.scan_progress['discovered_services']} found)")
                    
                    return result
            
            # Run all scans concurrently
            tasks = [scan_target(target) for target in scan_targets]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Collect successful results
            for result in results:
                if isinstance(result, dict) and result:
                    discovered.append(result)
                    self.scan_progress['discovered_services'] += 1
            
            # Update progress
            self.scan_progress['end_time'] = datetime.now()
            self.scan_progress['scanned_hosts'] = len(hosts)
            
            # Store discovered services in database
            await self._store_discovered_services(discovered)
            
            logger.info(f"Network discovery completed: {len(discovered)} DICOM services found")
            return discovered
            
        except Exception as e:
            logger.error(f"Error during network discovery: {e}")
            return []
    
    async def _scan_host_port(
        self, 
        host: str, 
        port: int, 
        ae_title_pattern: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Scan a specific host:port combination for DICOM service
        
        Args:
            host: IP address or hostname
            port: Port number
            ae_title_pattern: AE title pattern to match
            
        Returns:
            Dictionary with service info if found, None otherwise
        """
        try:
            # First check if port is open
            if not await self._is_port_open(host, port):
                return None
            
            # Try DICOM C-ECHO verification
            verification_result = await self._verify_dicom_service(host, port)
            if verification_result:
                service_info = {
                    'ip_address': host,
                    'port': port,
                    'ae_title': verification_result.get('ae_title', 'UNKNOWN'),
                    'verified': True,
                    'response_time': verification_result.get('response_time', 0),
                    'discovered_at': datetime.now().isoformat(),
                    'service_type': 'DICOM'
                }
                
                # Check AE title pattern if provided
                if ae_title_pattern:
                    ae_title = service_info['ae_title']
                    if ae_title_pattern.upper() not in ae_title.upper():
                        return None
                
                logger.debug(f"DICOM service discovered: {host}:{port} (AE: {service_info['ae_title']})")
                return service_info
            
            return None
            
        except Exception as e:
            logger.debug(f"Error scanning {host}:{port}: {e}")
            return None
    
    async def _is_port_open(self, host: str, port: int, timeout: float = 2.0) -> bool:
        """
        Check if a port is open on a host
        
        Args:
            host: IP address or hostname
            port: Port number
            timeout: Connection timeout in seconds
            
        Returns:
            True if port is open, False otherwise
        """
        try:
            # Use asyncio to create a connection with timeout
            future = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(future, timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError):
            return False
    
    async def _verify_dicom_service(self, host: str, port: int) -> Optional[Dict[str, Any]]:
        """
        Verify DICOM service using C-ECHO
        
        Args:
            host: IP address or hostname
            port: Port number
            
        Returns:
            Dictionary with verification results if successful, None otherwise
        """
        try:
            start_time = datetime.now()
            
            # Try to establish association with a generic AE title first
            assoc = self.ae.associate(
                host, 
                port, 
                ae_title='ANY-SCP'  # Generic AE title for discovery
            )
            
            if assoc.is_established:
                # Send C-ECHO request
                status = assoc.send_c_echo()
                end_time = datetime.now()
                response_time = (end_time - start_time).total_seconds()
                
                # Get remote AE title
                remote_ae = assoc.acceptor.ae_title if assoc.acceptor else 'UNKNOWN'
                
                assoc.release()
                
                if status.Status == 0x0000:  # Success
                    return {
                        'ae_title': remote_ae,
                        'response_time': response_time,
                        'status': 'verified'
                    }
                else:
                    logger.debug(f"C-ECHO failed for {host}:{port} - Status: {status.Status}")
                    return None
            else:
                logger.debug(f"Failed to establish association with {host}:{port}")
                return None
                
        except Exception as e:
            logger.debug(f"DICOM verification failed for {host}:{port}: {e}")
            return None
    
    async def discover_single_host(
        self, 
        host: str, 
        port: int, 
        ae_title: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Discover and verify a single DICOM host
        
        Args:
            host: IP address or hostname
            port: Port number
            ae_title: Expected AE title (optional)
            
        Returns:
            Service information if found, None otherwise
        """
        logger.info(f"Discovering DICOM service at {host}:{port}")
        
        try:
            # Reset progress for single host
            self.scan_progress = {
                'total_hosts': 1,
                'scanned_hosts': 0,
                'discovered_services': 0,
                'start_time': datetime.now(),
                'end_time': None
            }
            
            # Scan the specific host:port
            result = await self._scan_host_port(host, port, ae_title)
            
            # Update progress
            self.scan_progress['scanned_hosts'] = 1
            self.scan_progress['discovered_services'] = 1 if result else 0
            self.scan_progress['end_time'] = datetime.now()
            
            if result:
                # Store in database
                await self._store_discovered_services([result])
                logger.info(f"DICOM service verified: {host}:{port} (AE: {result['ae_title']})")
            else:
                logger.warning(f"No DICOM service found at {host}:{port}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error discovering host {host}:{port}: {e}")
            return None
    
    async def _store_discovered_services(self, services: List[Dict[str, Any]]):
        """
        Store discovered services in database
        
        Args:
            services: List of discovered service dictionaries
        """
        try:
            # Create table if it doesn't exist
            await self._ensure_discovery_table()
            
            # Store each service
            for service in services:
                query = """
                    INSERT OR REPLACE INTO dicom_discovered_services (
                        ip_address, port, ae_title, verified, response_time,
                        discovered_at, service_type, last_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """
                
                values = (
                    service['ip_address'],
                    service['port'],
                    service['ae_title'],
                    service['verified'],
                    service['response_time'],
                    service['discovered_at'],
                    service['service_type'],
                    datetime.now().isoformat()
                )
                
                await self.db_manager.execute_query(query, values)
            
            logger.info(f"Stored {len(services)} discovered services in database")
            
        except Exception as e:
            logger.error(f"Error storing discovered services: {e}")
    
    async def _ensure_discovery_table(self):
        """Ensure the discovery table exists"""
        create_table_query = """
            CREATE TABLE IF NOT EXISTS dicom_discovered_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                port INTEGER NOT NULL,
                ae_title TEXT,
                verified BOOLEAN DEFAULT FALSE,
                response_time REAL,
                discovered_at TEXT,
                service_type TEXT DEFAULT 'DICOM',
                last_verified TEXT,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ip_address, port)
            )
        """
        
        await self.db_manager.execute_query(create_table_query)
        
        # Create index for faster lookups
        index_query = "CREATE INDEX IF NOT EXISTS idx_ip_port ON dicom_discovered_services(ip_address, port)"
        await self.db_manager.execute_query(index_query)
    
    def get_scan_progress(self) -> Dict[str, Any]:
        """
        Get current scan progress
        
        Returns:
            Dictionary with scan progress information
        """
        progress = self.scan_progress.copy()
        
        if progress['start_time'] and progress['end_time']:
            duration = progress['end_time'] - progress['start_time']
            progress['duration_seconds'] = duration.total_seconds()
        elif progress['start_time']:
            duration = datetime.now() - progress['start_time']
            progress['duration_seconds'] = duration.total_seconds()
            progress['estimated_completion'] = None  # Could calculate based on progress
        
        return progress
    
    async def get_discovered_services(
        self, 
        verified_only: bool = True,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get discovered services from database
        
        Args:
            verified_only: Return only verified services
            limit: Maximum number of services to return
            
        Returns:
            List of discovered services
        """
        try:
            where_clause = "WHERE verified = TRUE" if verified_only else ""
            limit_clause = f"LIMIT {limit}" if limit else ""
            
            query = f"""
                SELECT * FROM dicom_discovered_services 
                {where_clause}
                ORDER BY last_verified DESC, discovered_at DESC
                {limit_clause}
            """
            
            results = await self.db_manager.execute_query(query)
            return [dict(row) for row in results] if results else []
            
        except Exception as e:
            logger.error(f"Error retrieving discovered services: {e}")
            return []
    
    async def discover_by_time_range(
        self,
        host: str,
        port: int,
        ae_title: str,
        hours_back: int = 24,
        auto_backoff: bool = True
    ) -> Dict[str, Any]:
        """
        Discover DICOM studies using C-FIND with time-based queries
        Implements backoff logic when hitting common result limits
        
        Args:
            host: DICOM host IP or hostname
            port: DICOM port
            ae_title: Target AE title
            hours_back: Hours to search back from now
            auto_backoff: Enable automatic backoff on suspected limits
            
        Returns:
            Dictionary with discovery results and metadata
        """
        logger.info(f"Starting time-based discovery on {host}:{port} (AE: {ae_title})")
        
        try:
            start_time = datetime.now()
            end_time = start_time
            search_start = start_time - timedelta(hours=hours_back)
            
            discovery_result = {
                'host': host,
                'port': port,
                'ae_title': ae_title,
                'search_start': search_start.isoformat(),
                'search_end': end_time.isoformat(),
                'hours_searched': hours_back,
                'total_studies': 0,
                'total_series': 0,
                'queries_performed': 0,
                'backoff_triggered': False,
                'final_time_range_hours': hours_back,
                'discovery_method': 'time_based_cfind',
                'queries': []
            }
            
            # Perform initial query
            query_result = await self._perform_cfind_time_query(
                host, port, ae_title, search_start, end_time
            )
            
            discovery_result['queries'].append(query_result)
            discovery_result['queries_performed'] = 1
            
            if not query_result['success']:
                discovery_result['error'] = query_result['error']
                return discovery_result
            
            study_count = query_result['study_count']
            series_count = query_result['series_count']
            
            discovery_result['total_studies'] = study_count
            discovery_result['total_series'] = series_count
            
            # Check if we hit a common limit threshold
            if auto_backoff and self._is_likely_limit_hit(study_count):
                logger.info(f"Potential limit detected ({study_count} studies). Starting backoff strategy.")
                
                backoff_result = await self._perform_backoff_discovery(
                    host, port, ae_title, start_time, hours_back
                )
                
                discovery_result.update(backoff_result)
                discovery_result['backoff_triggered'] = True
            
            # Store discovery results
            await self._store_time_discovery_result(discovery_result)
            
            logger.info(f"Time-based discovery completed: {discovery_result['total_studies']} studies found")
            return discovery_result
            
        except Exception as e:
            logger.error(f"Error in time-based discovery: {e}")
            return {
                'host': host,
                'port': port,
                'ae_title': ae_title,
                'error': str(e),
                'success': False
            }
    
    def _is_likely_limit_hit(self, count: int) -> bool:
        """
        Check if the result count suggests we hit a query limit
        
        Args:
            count: Number of results returned
            
        Returns:
            True if count suggests a limit was hit
        """
        # Common DICOM query limits (round numbers and powers of 2)
        for threshold in self.time_discovery_config['limit_thresholds']:
            if count == threshold:
                return True
                
        # Also check if it's a "suspicious" round number
        if count > 0 and count % 100 == 0 and count >= 100:
            return True
            
        return False
    
    async def _perform_backoff_discovery(
        self,
        host: str,
        port: int,
        ae_title: str,
        end_time: datetime,
        original_hours: int
    ) -> Dict[str, Any]:
        """
        Perform discovery with progressively smaller time ranges
        
        Args:
            host: DICOM host
            port: DICOM port
            ae_title: Target AE title
            end_time: End time for searches
            original_hours: Original time range in hours
            
        Returns:
            Dictionary with backoff discovery results
        """
        backoff_result = {
            'total_studies': 0,
            'total_series': 0,
            'queries_performed': 0,
            'final_time_range_hours': original_hours,
            'queries': [],
            'backoff_attempts': []
        }
        
        # Try progressively smaller time ranges
        for attempt, hours in enumerate(self.time_discovery_config['backoff_ranges']):
            if attempt >= self.time_discovery_config['max_attempts']:
                break
                
            logger.info(f"Backoff attempt {attempt + 1}: searching last {hours} hours")
            
            search_start = end_time - timedelta(hours=hours)
            
            query_result = await self._perform_cfind_time_query(
                host, port, ae_title, search_start, end_time
            )
            
            backoff_result['queries'].append(query_result)
            backoff_result['queries_performed'] += 1
            
            backoff_attempt = {
                'attempt': attempt + 1,
                'hours': hours,
                'study_count': query_result['study_count'],
                'series_count': query_result['series_count'],
                'success': query_result['success']
            }
            
            backoff_result['backoff_attempts'].append(backoff_attempt)
            
            if query_result['success']:
                study_count = query_result['study_count']
                series_count = query_result['series_count']
                
                # If we get a non-limit result, use this as our final count
                if not self._is_likely_limit_hit(study_count):
                    backoff_result['total_studies'] = study_count
                    backoff_result['total_series'] = series_count
                    backoff_result['final_time_range_hours'] = hours
                    
                    logger.info(f"Backoff successful: found {study_count} studies in {hours} hours (non-limit result)")
                    break
                else:
                    logger.info(f"Still hitting limit at {hours} hours ({study_count} studies)")
            else:
                logger.warning(f"Query failed at {hours} hours: {query_result['error']}")
        
        return backoff_result
    
    async def _perform_cfind_time_query(
        self,
        host: str,
        port: int,
        ae_title: str,
        start_time: datetime,
        end_time: datetime
    ) -> Dict[str, Any]:
        """
        Perform a C-FIND query for a specific time range
        
        Args:
            host: DICOM host
            port: DICOM port
            ae_title: Target AE title
            start_time: Start of time range
            end_time: End of time range
            
        Returns:
            Dictionary with query results
        """
        try:
            # Format dates for DICOM query (YYYYMMDD format)
            start_date = start_time.strftime("%Y%m%d")
            end_date = end_time.strftime("%Y%m%d")
            date_range = f"{start_date}-{end_date}"
            
            logger.debug(f"Performing C-FIND query: {host}:{port} for date range {date_range}")
            
            # Use dcmtk findscu for the query
            cmd = [
                '/usr/bin/findscu',
                '-aet', 'DISCOVERY_SCU',
                '-aec', ae_title,
                '-S',  # Study level query
                '-k', 'QueryRetrieveLevel=STUDY',
                '-k', f'StudyDate={date_range}',
                '-k', 'PatientName=',
                '-k', 'StudyInstanceUID=',
                '-k', 'StudyDescription=',
                '-k', 'StudyTime=',
                '-k', 'PatientID=',
                '-k', 'NumberOfStudyRelatedSeries=',
                host,
                str(port)
            ]
            
            start_query_time = datetime.now()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            end_query_time = datetime.now()
            
            query_duration = (end_query_time - start_query_time).total_seconds()
            
            if result.returncode == 0:
                # Count studies and series from output
                study_count = result.stdout.count('# Dicom-Data-Set')
                
                # Try to extract series count from NumberOfStudyRelatedSeries
                series_count = 0
                for line in result.stdout.split('\n'):
                    if 'NumberOfStudyRelatedSeries' in line:
                        # Extract number from the line
                        match = re.search(r'\[(\d+)\]', line)
                        if match:
                            series_count += int(match.group(1))
                
                return {
                    'success': True,
                    'study_count': study_count,
                    'series_count': series_count,
                    'query_duration': query_duration,
                    'date_range': date_range,
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat(),
                    'raw_output_length': len(result.stdout)
                }
            else:
                error_msg = result.stderr or "Unknown error"
                return {
                    'success': False,
                    'error': error_msg,
                    'study_count': 0,
                    'series_count': 0,
                    'query_duration': query_duration,
                    'date_range': date_range
                }
                
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Query timeout',
                'study_count': 0,
                'series_count': 0,
                'query_duration': 60.0,
                'date_range': f"{start_date}-{end_date}"
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'study_count': 0,
                'series_count': 0,
                'query_duration': 0.0,
                'date_range': f"{start_date}-{end_date}" if 'start_date' in locals() else 'unknown'
            }
    
    async def _store_time_discovery_result(self, result: Dict[str, Any]):
        """
        Store time-based discovery results in database
        
        Args:
            result: Discovery result dictionary
        """
        try:
            # Ensure table exists
            await self._ensure_time_discovery_table()
            
            query = """
                INSERT INTO dicom_time_discovery_results (
                    host, port, ae_title, search_start, search_end, 
                    hours_searched, total_studies, total_series,
                    queries_performed, backoff_triggered, final_time_range_hours,
                    discovery_method, result_data, discovered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            values = (
                result['host'],
                result['port'],
                result['ae_title'],
                result['search_start'],
                result['search_end'],
                result['hours_searched'],
                result['total_studies'],
                result['total_series'],
                result['queries_performed'],
                result['backoff_triggered'],
                result['final_time_range_hours'],
                result['discovery_method'],
                json.dumps(result),
                datetime.now().isoformat()
            )
            
            await self.db_manager.execute_query(query, values)
            logger.debug("Time discovery results stored in database")
            
        except Exception as e:
            logger.error(f"Error storing time discovery results: {e}")
    
    async def _ensure_time_discovery_table(self):
        """Ensure the time discovery results table exists"""
        create_table_query = """
            CREATE TABLE IF NOT EXISTS dicom_time_discovery_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                ae_title TEXT NOT NULL,
                search_start TEXT NOT NULL,
                search_end TEXT NOT NULL,
                hours_searched REAL,
                total_studies INTEGER,
                total_series INTEGER,
                queries_performed INTEGER,
                backoff_triggered BOOLEAN,
                final_time_range_hours REAL,
                discovery_method TEXT,
                result_data TEXT,  -- JSON of full result
                discovered_at TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        
        await self.db_manager.execute_query(create_table_query)
        
        # Create index for faster lookups
        index_query = "CREATE INDEX IF NOT EXISTS idx_time_discovery_host_port ON dicom_time_discovery_results(host, port, discovered_at)"
        await self.db_manager.execute_query(index_query)


__all__ = ['DICOMDiscoveryService']
