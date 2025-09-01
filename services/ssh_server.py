"""
SSH Server Service for Migration Service

SSH server with AILoop integration, providing secure remote access to the AI assistant.
Supports both password and public key authentication.
"""

import asyncio
import os
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List

try:
    import asyncssh
    from asyncssh import SSHKey, SSHAuthorizedKeys
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False
    asyncssh = None
    SSHKey = None
    SSHAuthorizedKeys = None

from core.logging import get_logger
from core.process_manager import ProcessManager
from core.config import Settings
from core.ai_loop import AIService
from core.ssl_manager import SSLManager

logger = get_logger(__name__)


class AILoopSSHSession:
    """SSH session that provides AI Loop interaction"""
    
    def __init__(self, ai_service: AIService, settings: Settings):
        self.ai_service = ai_service
        self.settings = settings
        self.session_active = True
        
    async def handle_session(self, process: 'asyncssh.SSHServerProcess') -> None:
        """Handle an SSH session with AILoop integration"""
        try:
            # Send welcome banner
            process.stdout.write(self.settings.ssh.ailoop_banner)
            process.stdout.write("\n")
            
            # Initialize AI service if not already done
            if self.ai_service and not hasattr(self.ai_service, 'available_providers'):
                await self.ai_service.initialize()
            
            # Main interaction loop
            while self.session_active:
                try:
                    # Display prompt
                    process.stdout.write(self.settings.ssh.ailoop_prompt)
                    
                    # Read user input
                    try:
                        line = await asyncio.wait_for(
                            process.stdin.readline(),
                            timeout=self.settings.ssh.connection_timeout
                        )
                    except asyncio.TimeoutError:
                        process.stdout.write("\nSession timeout. Goodbye!\n")
                        break
                    
                    if not line:
                        break
                    
                    user_input = line.strip()
                    
                    if not user_input:
                        continue
                    
                    # Process input through AI service if available
                    if self.ai_service:
                        response = await self.ai_service.process_input(user_input)
                    else:
                        response = "AI service not available. Basic commands only."
                    
                    # Handle special responses
                    if response == "QUIT_REQUESTED":
                        process.stdout.write("Goodbye!\n")
                        break
                    
                    # Send response
                    process.stdout.write(f"\n{response}\n\n")
                    
                except Exception as e:
                    logger.error(f"Error in SSH session loop: {e}")
                    process.stdout.write(f"\nError: {str(e)}\n\n")
                    continue
                    
        except Exception as e:
            logger.error(f"SSH session error: {e}")
            process.stdout.write(f"\nSession error: {str(e)}\n")
        finally:
            self.session_active = False
            process.exit(0)


class SSHServer:
    """SSH Server with AILoop integration"""
    
    def __init__(self, settings: Settings, process_manager: ProcessManager):
        """Initialize SSH server"""
        self.settings = settings
        self.process_manager = process_manager
        self.is_running = False
        self.server = None
        self.ai_service = None
        self.authorized_keys = None
        self.host_key = None
        
        if not SSH_AVAILABLE:
            logger.warning("asyncssh not available. SSH server will be disabled.")
            logger.info("Install with: pip install asyncssh")
            return
            
        logger.info(f"SSH Server initialized on port {settings.ssh.ssh_port}")
        
    async def _setup_host_key(self) -> bool:
        """Set up SSH host key"""
        try:
            host_key_path = Path(self.settings.ssh.ssh_host_key or "etc/key/ssh_host_key")
            host_key_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Generate host key if it doesn't exist
            if not host_key_path.exists():
                logger.info("Generating SSH host key...")
                
                if self.settings.ssh.ssh_host_key_type == "ed25519":
                    key = asyncssh.generate_private_key('ssh-ed25519')
                else:
                    key = asyncssh.generate_private_key('ssh-rsa', key_size=2048)
                
                # Write private key
                with open(host_key_path, 'wb') as f:
                    f.write(key.export_private_key())
                os.chmod(host_key_path, 0o600)
                
                # Write public key
                pub_key_path = host_key_path.with_suffix('.pub')
                with open(pub_key_path, 'wb') as f:
                    f.write(key.export_public_key())
                os.chmod(pub_key_path, 0o644)
                
                logger.info(f"SSH host key generated: {host_key_path}")
            
            # Load host key
            self.host_key = asyncssh.read_private_key(str(host_key_path))
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup SSH host key: {e}")
            return False
            
    async def _setup_authorized_keys(self) -> bool:
        """Set up authorized keys for public key authentication"""
        try:
            if not self.settings.ssh.ssh_allow_public_key:
                return True
                
            auth_keys_path = Path(self.settings.ssh.ssh_authorized_keys or "etc/key/authorized_keys")
            auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create empty authorized_keys file if it doesn't exist
            if not auth_keys_path.exists():
                logger.info("Creating empty authorized_keys file")
                logger.info(f"Add public keys to: {auth_keys_path}")
                with open(auth_keys_path, 'w') as f:
                    f.write("# Add SSH public keys here, one per line\n")
                os.chmod(auth_keys_path, 0o600)
            
            # Load authorized keys
            try:
                self.authorized_keys = asyncssh.read_authorized_keys(str(auth_keys_path))
                logger.info(f"Loaded authorized keys from: {auth_keys_path}")
            except Exception as e:
                logger.warning(f"Could not load authorized keys: {e}")
                self.authorized_keys = None
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup authorized keys: {e}")
            return False
    
    async def _authenticate_password(self, username: str, password: str) -> bool:
        """Authenticate using password from database"""
        if not self.settings.ssh.ssh_allow_password:
            return False
            
        try:
            # Use database authentication
            result = await self.process_manager.db_manager.check_user(username, password)
            
            if result:
                logger.info(f"SSH password authentication successful for user: {username}")
                return True
            else:
                logger.warning(f"SSH password authentication failed for user: {username}")
                return False
                
        except Exception as e:
            logger.error(f"SSH password authentication error for user {username}: {e}")
            return False
    
    def _authenticate_public_key(self, username: str, key: SSHKey) -> bool:
        """Authenticate using public key"""
        if not self.settings.ssh.ssh_allow_public_key or not self.authorized_keys:
            return False
            
        try:
            # Check if the key is in authorized_keys
            if self.authorized_keys.validate(key, username):
                logger.info(f"Public key authentication successful for user: {username}")
                return True
            else:
                logger.warning(f"Public key authentication failed for user: {username}")
                return False
        except Exception as e:
            logger.error(f"Error in public key authentication: {e}")
            return False
    
    async def _handle_client(self, process: 'asyncssh.SSHServerProcess') -> None:
        """Handle incoming SSH client connection"""
        try:
            logger.info(f"SSH client connected from {process.get_extra_info('peername')}")
            
            # Get AI service from process manager
            ai_service = getattr(self.process_manager, 'ai_service', None)
            
            # Create and run AI Loop session
            session = AILoopSSHSession(ai_service, self.settings)
            await session.handle_session(process)
            
        except Exception as e:
            logger.error(f"Error handling SSH client: {e}")
        finally:
            logger.info("SSH client disconnected")
    
    async def start(self) -> bool:
        """Start SSH server"""
        if not SSH_AVAILABLE:
            logger.error("Cannot start SSH server: asyncssh not available")
            return False
            
        if self.is_running:
            return True
            
        if not self.settings.ssh.ssh_enabled:
            logger.info("SSH server is disabled in configuration")
            return False
        
        try:
            # Setup host key and authorized keys
            if not await self._setup_host_key():
                return False
                
            if not await self._setup_authorized_keys():
                return False
            
            # Define authentication function
            async def auth_completed(username: str, password: Optional[str] = None, 
                                   public_key: Optional[SSHKey] = None) -> bool:
                if not self.settings.ssh.ssh_require_auth:
                    logger.info(f"Authentication bypassed for user: {username}")
                    return True
                    
                # Try public key first, then password
                if public_key and self._authenticate_public_key(username, public_key):
                    return True
                    
                if password and await self._authenticate_password(username, password):
                    return True
                    
                return False
            
            # Start SSH server
            self.server = await asyncssh.create_server(
                self._handle_client,
                host='0.0.0.0',
                port=self.settings.ssh.ssh_port,
                server_host_keys=[self.host_key],
                authorized_client_keys=auth_completed,
                process_factory=asyncssh.SSHServerProcess,
                encoding='utf-8',
                keepalive_interval=self.settings.ssh.keepalive_interval
            )
            
            self.is_running = True
            logger.info(f"✅ SSH server started on port {self.settings.ssh.ssh_port}")
            logger.info(f"Authentication methods: password={self.settings.ssh.ssh_allow_password}, " +
                       f"public_key={self.settings.ssh.ssh_allow_public_key}")
            if self.settings.ssh.ailoop_enabled:
                logger.info("AI Loop integration enabled - users will connect directly to AI assistant")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start SSH server: {e}")
            return False
    
    async def stop(self) -> bool:
        """Stop SSH server"""
        if not self.is_running:
            return True
        
        try:
            if self.server:
                self.server.close()
                await self.server.wait_closed()
                self.server = None
            
            self.is_running = False
            logger.info("SSH server stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping SSH server: {e}")
            return False


# Convenience function to start SSH server
async def start_ssh_server(settings: Settings, process_manager: ProcessManager) -> Optional[SSHServer]:
    """
    Start SSH server with AILoop integration
    
    Args:
        settings: Application settings
        process_manager: Process manager instance
        
    Returns:
        SSHServer instance if started successfully, None otherwise
    """
    if not SSH_AVAILABLE:
        logger.warning("SSH server not available. Install with: pip install asyncssh")
        return None
        
    server = SSHServer(settings, process_manager)
    
    if await server.start():
        return server
    else:
        return None


__all__ = ['SSHServer', 'AILoopSSHSession', 'start_ssh_server']
