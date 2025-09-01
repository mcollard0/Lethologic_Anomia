"""
Web Interface Service for Migration Service

FastAPI-based web interface providing REST API, WebSocket support, 
speech interface, and system management.
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query, Form, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from starlette.requests import Request
from starlette.websockets import WebSocket
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
import uvicorn
import ssl
from pathlib import Path

from core.custom_logging import get_logger, setup_logging
from core.process_manager import ProcessManager, ProcessType, ProcessState
from core.config import Settings
from core.ssl_manager import SSLManager

logger = get_logger(__name__)

# Security and authentication models
security = HTTPBearer(auto_error=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    enabled: bool
    created_at: str
    updated_at: str


class CreateUserRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    username: str
    old_password: str
    new_password: str


class WebSocketManager:
    """Manage WebSocket connections for real-time updates"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected: {websocket.client}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected: {websocket.client}")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send WebSocket message: {e}")
                disconnected.append(connection)
        
        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect(connection)


def create_app(process_manager: ProcessManager) -> FastAPI:
    """
    Create and configure the FastAPI application
    
    Args:
        process_manager: Process manager instance
        
    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Migration Service Web Interface",
        description="Medical Imaging Migration Service with AI",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc"
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # WebSocket manager
    ws_manager = WebSocketManager()
    
    # Static files and templates
    static_dir = Path(__file__).parent.parent / "static"
    template_dir = Path(__file__).parent.parent / "templates"
    
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    
    if template_dir.exists():
        templates = Jinja2Templates(directory=str(template_dir))
    else:
        templates = None
    
    # Authentication dependency
    async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Get current authenticated user from token"""
        if not credentials or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # For web UI, we use simple token-based auth (username as token)
        # In production, you'd want proper JWT tokens
        username = credentials.credentials
        
        # Verify user exists and is enabled
        user_info = await process_manager.db_manager.get_user_info(username)
        if not user_info or user_info.get('deleted', False) or not user_info.get('enabled', False):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
        
        return user_info
    
    # Optional authentication (for endpoints that work with or without auth)
    async def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Get current user if authenticated, otherwise None"""
        if not credentials or not credentials.credentials:
            return None
        
        try:
            return await get_current_user(credentials)
        except HTTPException:
            return None
    
    # === AUTHENTICATION ENDPOINTS ===
    
    @app.post("/auth/login")
    async def login(login_request: LoginRequest):
        """Login endpoint"""
        try:
            # Check user credentials
            if await process_manager.db_manager.check_user(login_request.username, login_request.password):
                # Get user info
                user_info = await process_manager.db_manager.get_user_info(login_request.username)
                
                # For simplicity, return username as token
                # In production, use proper JWT tokens
                return {
                    "access_token": login_request.username,
                    "token_type": "bearer",
                    "user": {
                        "id": user_info["id"],
                        "username": user_info["username"],
                        "enabled": user_info["enabled"],
                        "created_at": user_info["created_at"].isoformat() if isinstance(user_info["created_at"], datetime) else str(user_info["created_at"])
                    }
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials"
                )
        except Exception as e:
            logger.error(f"Login error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Login failed"
            )
    
    @app.post("/auth/create-user")
    async def create_user(create_request: CreateUserRequest, current_user = Depends(get_current_user)):
        """Create new user (requires authentication)"""
        try:
            success = await process_manager.db_manager.create_user(
                create_request.username, 
                create_request.password
            )
            
            if success:
                return {"message": f"User '{create_request.username}' created successfully"}
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to create user (username may already exist)"
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Create user error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user"
            )
    
    @app.post("/auth/change-password")
    async def change_password(password_request: ChangePasswordRequest, current_user = Depends(get_current_user)):
        """Change user password (requires authentication)"""
        try:
            success = await process_manager.db_manager.change_password(
                password_request.username,
                password_request.old_password,
                password_request.new_password
            )
            
            if success:
                return {"message": "Password changed successfully"}
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to change password (invalid current password or user not found)"
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Change password error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to change password"
            )
    
    @app.delete("/auth/delete-user/{username}")
    async def delete_user(username: str, current_user = Depends(get_current_user)):
        """Delete user (requires authentication)"""
        try:
            success = await process_manager.db_manager.delete_user(username)
            
            if success:
                return {"message": f"User '{username}' deleted successfully"}
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Delete user error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user"
            )
    
    @app.get("/auth/users", response_model=List[UserResponse])
    async def list_users(current_user = Depends(get_current_user)):
        """List all users (requires authentication)"""
        try:
            users = await process_manager.db_manager.list_users()
            return [
                {
                    "id": user["id"],
                    "username": user["username"],
                    "enabled": user["enabled"],
                    "created_at": user["created_at"].isoformat() if isinstance(user["created_at"], datetime) else str(user["created_at"]),
                    "updated_at": user["updated_at"].isoformat() if isinstance(user["updated_at"], datetime) else str(user["updated_at"])
                }
                for user in users
            ]
        except Exception as e:
            logger.error(f"List users error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to list users"
            )
    
    # === PUBLIC ENDPOINTS ===
    
    # Home page (public)
    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        """Main dashboard page"""
        if templates:
            return templates.TemplateResponse("dashboard.html", {"request": request})
        else:
            # Return basic HTML with login form
            html_content = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Migration Service Dashboard</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; }
                    .header { background: #2c3e50; color: white; padding: 20px; border-radius: 5px; }
                    .section { margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
                    .button { background: #3498db; color: white; padding: 10px 20px; border: none; border-radius: 3px; cursor: pointer; text-decoration: none; display: inline-block; }
                    .login-form { max-width: 400px; }
                    .form-group { margin: 10px 0; }
                    .form-group label { display: block; margin-bottom: 5px; }
                    .form-group input { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 3px; }
                    .status-running { color: green; }
                    .status-stopped { color: red; }
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>Migration Service Dashboard</h1>
                    <p>Medical Imaging Migration Service with AI</p>
                </div>
                
                <div class="section">
                    <h2>Login</h2>
                    <form class="login-form" id="loginForm">
                        <div class="form-group">
                            <label for="username">Username:</label>
                            <input type="text" id="username" name="username" required>
                        </div>
                        <div class="form-group">
                            <label for="password">Password:</label>
                            <input type="password" id="password" name="password" required>
                        </div>
                        <div class="form-group">
                            <button type="submit" class="button">Login</button>
                        </div>
                    </form>
                    <div id="message"></div>
                </div>
                
                <div class="section">
                    <h2>Quick Links</h2>
                    <a href="/api/docs" class="button">API Documentation</a>
                    <a href="/api/health" class="button">Health Check</a>
                </div>
                
                <script>
                document.getElementById('loginForm').addEventListener('submit', async function(e) {
                    e.preventDefault();
                    const username = document.getElementById('username').value;
                    const password = document.getElementById('password').value;
                    
                    try {
                        const response = await fetch('/auth/login', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ username, password })
                        });
                        
                        const data = await response.json();
                        
                        if (response.ok) {
                            document.getElementById('message').innerHTML = '<p style="color: green;">Login successful! Token: ' + data.access_token + '</p>';
                            localStorage.setItem('auth_token', data.access_token);
                        } else {
                            document.getElementById('message').innerHTML = '<p style="color: red;">Login failed: ' + data.detail + '</p>';
                        }
                    } catch (error) {
                        document.getElementById('message').innerHTML = '<p style="color: red;">Login error: ' + error.message + '</p>';
                    }
                });
                </script>
            </body>
            </html>
            """
            return HTMLResponse(html_content)
    
    # Health check endpoint (public)
    @app.get("/api/health")
    async def health_check():
        """Health check endpoint"""
        try:
            return {
                "status": "healthy",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error in health check: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    return app


def create_ssl_context(settings: Settings) -> ssl.SSLContext:
    """
    Create SSL context with TLS 1.2+ enforcement
    
    Args:
        settings: Application settings
        
    Returns:
        Configured SSL context
    """
    # Initialize SSL manager to ensure certificates exist
    ssl_manager = SSLManager()
    ssl_manager.setup_ssl_infrastructure()
    
    # Create SSL context
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    
    # Set minimum and maximum TLS versions
    if settings.web.ssl_min_version == "TLSv1_2":
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    elif settings.web.ssl_min_version == "TLSv1_3":
        context.minimum_version = ssl.TLSVersion.TLSv1_3
    
    if settings.web.ssl_max_version == "TLSv1_2":
        context.maximum_version = ssl.TLSVersion.TLSv1_2
    elif settings.web.ssl_max_version == "TLSv1_3":
        context.maximum_version = ssl.TLSVersion.TLSv1_3
    
    # Load certificates
    cert_file = settings.web.ssl_certfile or "etc/key/certificate.pem"
    key_file = settings.web.ssl_keyfile or "etc/key/private.key"
    
    if not Path(cert_file).exists() or not Path(key_file).exists():
        logger.warning("SSL certificate or key file not found, generating self-signed certificate")
        ssl_manager.setup_ssl_infrastructure(force_regenerate=True)
    
    try:
        context.load_cert_chain(cert_file, key_file)
        logger.info(f"SSL certificate loaded: {cert_file}")
    except Exception as e:
        logger.error(f"Failed to load SSL certificate: {e}")
        raise
    
    # Set security options
    context.set_ciphers('HIGH:!aNULL:!eNULL:!EXPORT:!DES:!RC4:!MD5:!PSK:!SRP:!CAMELLIA')
    context.options |= ssl.OP_NO_SSLv2
    context.options |= ssl.OP_NO_SSLv3
    context.options |= ssl.OP_NO_TLSv1
    context.options |= ssl.OP_NO_TLSv1_1  # Disable TLS 1.0 and 1.1
    context.options |= ssl.OP_SINGLE_DH_USE
    context.options |= ssl.OP_SINGLE_ECDH_USE
    
    return context


async def start_web_server(process_manager: ProcessManager, settings: Settings) -> None:
    """
    Start the web server with SSL-only configuration
    
    Args:
        process_manager: Process manager instance
        settings: Application settings
    """
    if not settings.web.web_interface_enabled:
        logger.info("Web interface is disabled")
        return
    
    app = create_app(process_manager)
    
    # SSL configuration
    if settings.web.ssl_enabled and settings.web.ssl_only:
        ssl_context = create_ssl_context(settings)
        
        logger.info(f"Starting HTTPS-only web server on port {settings.web.web_port}")
        logger.info(f"TLS version range: {settings.web.ssl_min_version} - {settings.web.ssl_max_version}")
        
        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=settings.web.web_port,
            ssl_context=ssl_context,
            access_log=True,
            log_level="info"
        )
    else:
        logger.warning("SSL is not properly configured - this is not recommended for production!")
        config = uvicorn.Config(
            app=app,
            host="0.0.0.0", 
            port=settings.web.web_port,
            access_log=True,
            log_level="info"
        )
    
    server = uvicorn.Server(config)
    
    try:
        await server.serve()
    except Exception as e:
        logger.error(f"Web server error: {e}")
        raise


__all__ = ['create_app', 'WebSocketManager', 'start_web_server', 'create_ssl_context']
