import requests
import json
from typing import Dict, Any, Optional
import aiohttp


class CeleryHttpserverClient:
    """Synchronous version of Celery HTTP Server API client"""
    
    def __init__(
        self, 
        base_url: str = "http://celery-httpserver.dac.svc.cluster.local:8000",
        timeout: int = 300
    ):
        """
        Initialize client
        
        Args:
            base_url: API base URL
            timeout: Request timeout (seconds)
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
    
    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generic method for sending HTTP requests
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            payload: Request body data (optional)
            params: Query parameters (optional)
            
        Returns:
            API response result
            
        Raises:
            Exception: Request failed or JSON parsing failed
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        headers = {"Content-Type": "application/json"}
        
        try:
            request_kwargs = {
                "method": method,
                "url": url,
                "timeout": self.timeout,
                "headers": headers
            }
            
            if payload is not None:
                request_kwargs["json"] = payload
            
            if params is not None:
                request_kwargs["params"] = params
            
            # Create new session for each request
            with requests.Session() as session:
                response = session.request(**request_kwargs)
                response.raise_for_status()
                return response.json()
            
        except requests.RequestException as e:
            raise Exception(f"HTTP request failed: {e}")
        except json.JSONDecodeError as e:
            raise Exception(f"Response JSON parsing failed: {e}")

    def trigger_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Trigger a Celery task
        
        Args:
            data: Task data dictionary
            
        Returns:
            API response with task_id
            
        Example:
            >>> client = CeleryHttpserverClient()
            >>> result = client.trigger_task({
            ...     "operation": "AddOrUpdate",
            ...     "descriptor": {
            ...         "name": "dd-101",
            ...         "namespace": "dac"
            ...     }
            ... })
        """
        payload = {"data": data}
        endpoint = "/trigger_task"
        
        return self._make_request("POST", endpoint, payload)

    def semantic_group_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Trigger a semantic group task
        
        Args:
            data: Task data dictionary
            
        Returns:
            API response with task_id
            
        Example:
            >>> client = CeleryHttpserverClient()
            >>> result = client.semantic_group_task({
            ...     "operation": "AddOrUpdate",
            ...     "descriptor": {
            ...         "name": "dd-62",
            ...         "namespace": "dac"
            ...     }
            ... })
        """
        payload = {"data": data}
        endpoint = "/semantic_group_task"
        
        return self._make_request("POST", endpoint, payload)

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get task status by task_id
        
        Args:
            task_id: Task ID returned from trigger_task or semantic_group_task
            
        Returns:
            API response with task_id, status, and result
            
        Example:
            >>> client = CeleryHttpserverClient()
            >>> status = client.get_task_status("5db7f514-f966-4972-b982-73db22ef1576")
            >>> print(status["status"])  # PENDING, SUCCESS, FAILURE, etc.
        """
        endpoint = f"/task_status/{task_id}"
        
        return self._make_request("GET", endpoint)

    def health_check(self) -> bool:
        """
        Health check
        
        Returns:
            bool: Whether service is healthy
        """
        try:
            self.get_info()
            return True
        except Exception:
            return False

    def get_info(self) -> Dict[str, Any]:
        """
        Get service information
        
        Returns:
            API response with service info
        """
        endpoint = "/info"
        
        return self._make_request("GET", endpoint)

    def get_root(self) -> Dict[str, Any]:
        """
        Get root endpoint status
        
        Returns:
            API response with status
        """
        endpoint = "/"
        
        return self._make_request("GET", endpoint)

if __name__ == "__main__":
    import asyncio
    
    # Run synchronous example
    sync_main()
