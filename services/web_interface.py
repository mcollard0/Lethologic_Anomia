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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.requests import Request
from starlette.websockets import WebSocket
import uvicorn

from core.logging import get_logger
from core.process_manager import ProcessManager, ProcessType, ProcessState
from core.config import Settings

logger = get_logger(__name__)

# Security
security = HTTPBearer(auto_error=False)


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
    
    # Authentication dependency (basic for now)
    async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        # TODO: Implement proper authentication
        # For now, just check if token is provided
        if credentials and credentials.credentials:
            return {"username": "admin"}  # Placeholder
        return None
    
    # Home page
    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        """Main dashboard page"""
        if templates:
            return templates.TemplateResponse("dashboard.html", {"request": request})
        else:
            # Return basic HTML if no templates
            html_content = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Migration Service Dashboard</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; }
                    .header { background: #2c3e50; color: white; padding: 20px; border-radius: 5px; }
                    .section { margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
                    .button { background: #3498db; color: white; padding: 10px 20px; border: none; border-radius: 3px; cursor: pointer; }
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
                    <h2>Quick Links</h2>
                    <a href="/api/docs" class="button">API Documentation</a>
                    <a href="/processes" class="button">Process Status</a>
                    <a href="/dicom/search" class="button">DICOM Search</a>
                    <a href="/speech" class="button">Speech Interface</a>
                </div>
                
                <div class="section">
                    <h2>System Status</h2>
                    <p>Use the API endpoints to monitor and control the system.</p>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(html_content)
    
    # Health check endpoint
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


__all__ = ['create_app', 'WebSocketManager']
