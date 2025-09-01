"""
SSL/TLS Key Management Module

Handles SSL certificate and key pair generation, validation, and management
for secure DICOM communications.
"""

import os
import sys
import ipaddress
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import subprocess
from datetime import datetime, timedelta
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from cryptography import x509

from .custom_logging import get_logger

logger = get_logger(__name__)


class SSLManager:
    """SSL/TLS Key and Certificate Manager"""
    
    def __init__(self, key_directory: str = "etc/key"):
        """
        Initialize SSL Manager
        
        Args:
            key_directory: Directory to store SSL keys and certificates
        """
        self.key_directory = Path(key_directory)
        self.key_directory.mkdir(parents=True, exist_ok=True)
        
        self.private_key_file = self.key_directory / "private.key"
        self.public_key_file = self.key_directory / "public.key"
        self.certificate_file = self.key_directory / "certificate.pem"
        
        logger.info(f"SSL Manager initialized with key directory: {self.key_directory}")
    
    def generate_key_pair(self, key_size: int = 2048) -> bool:
        """
        Generate RSA key pair
        
        Args:
            key_size: RSA key size in bits (default: 2048)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Generating {key_size}-bit RSA key pair...")
            
            # Generate private key
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=key_size,
            )
            
            # Get public key
            public_key = private_key.public_key()
            
            # Serialize private key
            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            # Serialize public key
            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            
            # Write private key
            with open(self.private_key_file, 'wb') as f:
                f.write(private_pem)
            os.chmod(self.private_key_file, 0o600)  # Private key should be read-only by owner
            
            # Write public key
            with open(self.public_key_file, 'wb') as f:
                f.write(public_pem)
            os.chmod(self.public_key_file, 0o644)  # Public key can be read by others
            
            logger.info(f"✅ Key pair generated successfully")
            logger.info(f"   Private key: {self.private_key_file}")
            logger.info(f"   Public key: {self.public_key_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to generate key pair: {e}")
            return False
    
    def generate_self_signed_certificate(
        self,
        common_name: str = "localhost",
        organization: str = "Medical Imaging Migration Service",
        country: str = "US",
        validity_days: int = 365
    ) -> bool:
        """
        Generate self-signed certificate
        
        Args:
            common_name: Common name for certificate
            organization: Organization name
            country: Country code
            validity_days: Certificate validity in days
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Load private key
            if not self.private_key_file.exists():
                logger.error("Private key not found. Generate key pair first.")
                return False
            
            with open(self.private_key_file, 'rb') as f:
                private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                )
            
            # Create certificate subject and issuer
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, country),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
                x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            ])
            
            # Create certificate
            cert = x509.CertificateBuilder().subject_name(
                subject
            ).issuer_name(
                issuer
            ).public_key(
                private_key.public_key()
            ).serial_number(
                x509.random_serial_number()
            ).not_valid_before(
                datetime.utcnow()
            ).not_valid_after(
                datetime.utcnow() + timedelta(days=validity_days)
            ).add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.DNSName("*.localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.IPAddress(ipaddress.IPv6Address("::1")),
                ]),
                critical=False,
            ).sign(private_key, hashes.SHA256())
            
            # Write certificate
            with open(self.certificate_file, 'wb') as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            
            logger.info(f"✅ Self-signed certificate generated")
            logger.info(f"   Certificate: {self.certificate_file}")
            logger.info(f"   Common Name: {common_name}")
            logger.info(f"   Valid for: {validity_days} days")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to generate certificate: {e}")
            return False
    
    def load_private_key(self, key_file: Optional[str] = None) -> Optional[Any]:
        """
        Load private key from file
        
        Args:
            key_file: Path to private key file (default: use configured file)
            
        Returns:
            Private key object or None if failed
        """
        try:
            key_path = Path(key_file) if key_file else self.private_key_file
            
            if not key_path.exists():
                logger.error(f"Private key file not found: {key_path}")
                return None
            
            with open(key_path, 'rb') as f:
                private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                )
            
            logger.info(f"Private key loaded from: {key_path}")
            return private_key
            
        except Exception as e:
            logger.error(f"Failed to load private key: {e}")
            return None
    
    def load_certificate(self, cert_file: Optional[str] = None) -> Optional[Any]:
        """
        Load certificate from file
        
        Args:
            cert_file: Path to certificate file (default: use configured file)
            
        Returns:
            Certificate object or None if failed
        """
        try:
            cert_path = Path(cert_file) if cert_file else self.certificate_file
            
            if not cert_path.exists():
                logger.error(f"Certificate file not found: {cert_path}")
                return None
            
            with open(cert_path, 'rb') as f:
                cert = x509.load_pem_x509_certificate(f.read())
            
            logger.info(f"Certificate loaded from: {cert_path}")
            return cert
            
        except Exception as e:
            logger.error(f"Failed to load certificate: {e}")
            return None
    
    def validate_key_pair(self) -> bool:
        """
        Validate that private and public keys match
        
        Returns:
            True if keys are valid and match, False otherwise
        """
        try:
            # Load private key
            private_key = self.load_private_key()
            if not private_key:
                return False
            
            # Load public key
            if not self.public_key_file.exists():
                logger.error("Public key file not found")
                return False
            
            with open(self.public_key_file, 'rb') as f:
                public_key = serialization.load_pem_public_key(f.read())
            
            # Compare public keys
            private_public_key = private_key.public_key()
            
            private_pub_nums = private_public_key.public_numbers()
            public_nums = public_key.public_numbers()
            
            if private_pub_nums.n == public_nums.n and private_pub_nums.e == public_nums.e:
                logger.info("✅ Key pair validation successful")
                return True
            else:
                logger.error("❌ Key pair validation failed - keys don't match")
                return False
                
        except Exception as e:
            logger.error(f"Key pair validation error: {e}")
            return False
    
    def get_certificate_info(self) -> Optional[Dict[str, Any]]:
        """
        Get certificate information
        
        Returns:
            Dictionary with certificate details or None if failed
        """
        try:
            cert = self.load_certificate()
            if not cert:
                return None
            
            info = {
                'subject': cert.subject.rfc4514_string(),
                'issuer': cert.issuer.rfc4514_string(),
                'serial_number': str(cert.serial_number),
                'not_valid_before': cert.not_valid_before.isoformat(),
                'not_valid_after': cert.not_valid_after.isoformat(),
                'signature_algorithm': cert.signature_algorithm_oid._name,
                'is_expired': datetime.utcnow() > cert.not_valid_after,
                'days_until_expiry': (cert.not_valid_after - datetime.utcnow()).days
            }
            
            return info
            
        except Exception as e:
            logger.error(f"Failed to get certificate info: {e}")
            return None
    
    def setup_ssl_infrastructure(self, force_regenerate: bool = False) -> bool:
        """
        Set up complete SSL infrastructure
        
        Args:
            force_regenerate: Force regeneration even if files exist
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Setting up SSL infrastructure...")
            
            # Check if keys already exist
            if (self.private_key_file.exists() and 
                self.public_key_file.exists() and 
                not force_regenerate):
                logger.info("SSL keys already exist")
                
                if self.validate_key_pair():
                    logger.info("✅ Existing SSL infrastructure validated")
                    return True
                else:
                    logger.warning("Existing keys are invalid, regenerating...")
            
            # Generate new key pair
            if not self.generate_key_pair():
                return False
            
            # Validate key pair
            if not self.validate_key_pair():
                logger.error("Generated keys failed validation")
                return False
            
            # Generate self-signed certificate
            if not self.generate_self_signed_certificate():
                logger.warning("Failed to generate certificate, but keys are available")
            
            logger.info("✅ SSL infrastructure setup complete")
            return True
            
        except Exception as e:
            logger.error(f"SSL infrastructure setup failed: {e}")
            return False
    
    def get_ssl_config(self) -> Dict[str, str]:
        """
        Get SSL configuration for DICOM services
        
        Returns:
            Dictionary with SSL file paths
        """
        return {
            'private_key_file': str(self.private_key_file),
            'public_key_file': str(self.public_key_file),
            'certificate_file': str(self.certificate_file),
            'key_directory': str(self.key_directory)
        }


# Convenience functions
def setup_ssl(key_directory: str = "etc/key", force_regenerate: bool = False) -> bool:
    """
    Set up SSL infrastructure with default settings
    
    Args:
        key_directory: Directory for SSL keys
        force_regenerate: Force regeneration of keys
        
    Returns:
        True if successful, False otherwise
    """
    ssl_manager = SSLManager(key_directory)
    return ssl_manager.setup_ssl_infrastructure(force_regenerate)


def generate_keys(key_size: int = 2048, key_directory: str = "etc/key") -> bool:
    """
    Generate SSL key pair
    
    Args:
        key_size: RSA key size in bits
        key_directory: Directory for SSL keys
        
    Returns:
        True if successful, False otherwise
    """
    ssl_manager = SSLManager(key_directory)
    return ssl_manager.generate_key_pair(key_size)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="SSL Key Management")
    parser.add_argument("--generate", action="store_true", help="Generate new key pair")
    parser.add_argument("--validate", action="store_true", help="Validate existing keys")
    parser.add_argument("--setup", action="store_true", help="Setup complete SSL infrastructure")
    parser.add_argument("--info", action="store_true", help="Show certificate information")
    parser.add_argument("--key-size", type=int, default=2048, help="RSA key size (default: 2048)")
    parser.add_argument("--force", action="store_true", help="Force regeneration")
    
    args = parser.parse_args()
    
    ssl_manager = SSLManager()
    
    if args.generate:
        success = ssl_manager.generate_key_pair(args.key_size)
        sys.exit(0 if success else 1)
    
    elif args.validate:
        success = ssl_manager.validate_key_pair()
        sys.exit(0 if success else 1)
    
    elif args.setup:
        success = ssl_manager.setup_ssl_infrastructure(args.force)
        sys.exit(0 if success else 1)
    
    elif args.info:
        info = ssl_manager.get_certificate_info()
        if info:
            print("Certificate Information:")
            for key, value in info.items():
                print(f"  {key}: {value}")
        sys.exit(0 if info else 1)
    
    else:
        parser.print_help()
