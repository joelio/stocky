#!/usr/bin/env python3
"""
Stocky MCP Server - A friendly MCP server for searching royalty-free stock
images.

This server provides tools to search for stock images from Pexels and Unsplash.
"""
import logging
import os
import sys
import urllib.parse
import base64
import pycurl
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from abc import ABC, abstractmethod
from pathlib import Path
import io
import json
# Environment variables are handled by the MCP client

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP package not found. Please install it with: "
          "pip install mcp")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ImageResult:
    """Represents a single image search result with all metadata."""
    id: str
    title: str
    description: Optional[str]
    url: str
    thumbnail: str
    width: int
    height: int
    photographer: str
    photographer_url: Optional[str]
    source: str
    license: str
    attribution_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Initialize default values for mutable fields."""
        if self.tags is None:
            self.tags = []


class StockImageProvider(ABC):
    """Abstract base class for stock image providers."""

    def __init__(self, api_key: str):
        """Initialize provider with API key."""
        self.api_key = api_key
        self.session = None

    @abstractmethod
    def search(self, query: str, per_page: int = 20, page: int = 1,
               **kwargs) -> List[ImageResult]:
        """Search for images."""
        pass

    @abstractmethod
    def get_details(self, image_id: str) -> Optional[ImageResult]:
        """Get detailed information about a specific image."""
        pass

    def __enter__(self):
        """Create HTTP session on context manager entry."""
        # Using pycurl for HTTP requests
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close HTTP session on context manager exit."""
        if self.session:
            self.session.close()


class PexelsProvider(StockImageProvider):
    """Provider for Pexels image search API."""

    def __init__(self, api_key: str):
        """Initialize Pexels provider with API key."""
        if not api_key:
            raise ValueError(
                "Pexels API key is missing!\n"
                "Please set the PEXELS_API_KEY environment variable.\n"
                "You can get a free API key at: https://www.pexels.com/api/"
            )
        super().__init__(api_key)
        
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = True  # Just a placeholder to indicate session is active
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        self.session = None

    def search(self, query: str, per_page: int = 20, page: int = 1,
               **kwargs) -> List[ImageResult]:
        """Search Pexels for images."""
        if not self.session:
            raise RuntimeError(
                "Provider must be used within context manager"
            )

        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": self.api_key}
        params = {
            "query": query,
            "per_page": per_page,
            "page": page
        }

        try:
            # Use pycurl to make the request
            buffer = io.BytesIO()
            c = pycurl.Curl()

            # Build URL with parameters
            query_string = urllib.parse.urlencode(params)
            full_url = f"{url}?{query_string}"

            c.setopt(pycurl.URL, full_url)
            c.setopt(pycurl.WRITEDATA, buffer)
            header_list = [f"{k}: {v}" for k, v in headers.items()]
            c.setopt(pycurl.HTTPHEADER, header_list)
            c.perform()

            # Check status code
            status_code = c.getinfo(pycurl.HTTP_CODE)
            if status_code != 200:
                logger.error(f"Pexels API error: HTTP status {status_code}")
                return []

            c.close()

            # Parse JSON response
            response_data = buffer.getvalue().decode('utf-8')
            data = json.loads(response_data)
        except (pycurl.error, json.JSONDecodeError) as e:
            logger.error(f"Pexels API error: {e}")
            return []

            results = []
            for photo in data.get("photos", []):
                # Create attribution URL for Pexels
                # Using the photographer URL as attribution

                results.append(ImageResult(
                    id=f"pexels_{photo['id']}",
                    title=photo.get(
                        "alt", f"Photo by {photo['photographer']}"
                    ),
                    description=photo.get("alt", ""),
                    url=photo["src"]["large"],
                    thumbnail=photo["src"]["medium"],
                    width=photo["width"],
                    height=photo["height"],
                    photographer=photo["photographer"],
                    photographer_url=photo["photographer_url"],
                    source="Pexels",
                    license="Free to use, attribution appreciated",
                    tags=[photo.get("alt", "").lower()]
                    if photo.get("alt") else []
                ))
        except pycurl.error as e:
            logger.error(f"Pexels API error: {e}")
            return []
            
    def get_details(self, image_id: str) -> Optional[ImageResult]:  # noqa: E501
        """Get details for a specific Pexels image."""
        if not self.session:
            raise RuntimeError(
                "Provider must be used within context manager"
            )

        # Extract ID from our prefixed ID
        pexels_id = image_id.replace("pexels_", "")
        url = f"https://api.pexels.com/v1/photos/{pexels_id}"
        headers = {"Authorization": self.api_key}

        try:
            # Use pycurl to make the request
            buffer = io.BytesIO()
            c = pycurl.Curl()
            
            c.setopt(pycurl.URL, url)
            c.setopt(pycurl.WRITEDATA, buffer)
            header_list = [f"{k}: {v}" for k, v in headers.items()]
            c.setopt(pycurl.HTTPHEADER, header_list)
            c.perform()
            
            # Check status code
            status_code = c.getinfo(pycurl.HTTP_CODE)
            if status_code != 200:
                logger.error(f"Pexels API error: HTTP status {status_code}")
                return None
                
            c.close()
            
            # Parse JSON response
            response_data = buffer.getvalue().decode('utf-8')
            photo = json.loads(response_data)
            
            # Create attribution URL for Pexels
            attribution_url = photo["url"]
            
            return ImageResult(
                id=f"pexels_{photo['id']}",
                title=photo.get("alt", f"Photo by {photo['photographer']}"),
                description=photo.get("alt", ""),
                url=photo["src"]["large"],
                thumbnail=photo["src"]["medium"],
                width=photo["width"],
                height=photo["height"],
                photographer=photo["photographer"],
                photographer_url=photo["photographer_url"],
                source="Pexels",
                license="Free to use, attribution appreciated",
                attribution_url=attribution_url,
                tags=[photo.get("alt", "").lower()] if photo.get("alt") else []
            )
        except pycurl.error as e:
            logger.error(f"Pexels API error: {e}")
            return None


class UnsplashProvider(StockImageProvider):
    """Provider for Unsplash API."""

    BASE_URL = "https://api.unsplash.com"

    def __init__(self, api_key: str):
        """Initialize Unsplash provider with API key."""
        if not api_key:
            raise ValueError(
                "Unsplash API key is missing!\n"
                "Please set the UNSPLASH_ACCESS_KEY environment "
                "variable.\n"
                "You can get a free API key at: "
                "https://unsplash.com/developers"
            )
        super().__init__(api_key)
        
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = True  # Just a placeholder to indicate session is active
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        self.session = None

    async def search(self, query: str, per_page: int = 20, page: int = 1,
                     **kwargs) -> List[ImageResult]:
        """Search Unsplash for images."""
        if not self.session:
            raise RuntimeError(
                "Provider must be used within async context manager"
            )

        url = "https://api.unsplash.com/search/photos"
        headers = {"Authorization": f"Client-ID {self.api_key}"}
        params = {
            "query": query,
            "per_page": per_page,
            "page": page
        }

        try:
            # Use pycurl to make the request
            buffer = io.BytesIO()
            c = pycurl.Curl()
            
            # Build URL with parameters
            query_string = urllib.parse.urlencode(params)
            full_url = f"{url}?{query_string}"
            
            c.setopt(pycurl.URL, full_url)
            c.setopt(pycurl.WRITEDATA, buffer)
            header_list = [f"{k}: {v}" for k, v in headers.items()]
            c.setopt(pycurl.HTTPHEADER, header_list)
            c.perform()
            
            # Check status code
            status_code = c.getinfo(pycurl.HTTP_CODE)
            if status_code != 200:
                logger.error(f"Unsplash API error: HTTP status {status_code}")
                return []
                
            c.close()
            
            # Parse JSON response
            response_data = buffer.getvalue().decode('utf-8')
            data = json.loads(response_data)

            results = []
            for photo in data.get("results", []):
                # Create attribution URL for Unsplash
                attribution_url = (
                    f"https://unsplash.com/photos/{photo['id']}"
                )

                results.append(ImageResult(
                    id=f"unsplash_{photo['id']}",
                    title=(photo.get("description", "Untitled")
                           or "Untitled"),
                    description=photo.get("alt_description", ""),
                    url=photo["urls"]["regular"],
                    thumbnail=photo["urls"]["small"],
                    width=photo["width"],
                    height=photo["height"],
                    photographer=photo["user"]["name"],
                    photographer_url=photo["user"]["links"]["html"],
                    source="Unsplash",
                    license="Free to use under Unsplash License",
                    attribution_url=attribution_url,
                    tags=[tag["title"] for tag in photo.get("tags", [])]
                ))
            return results
        except pycurl.error as e:
            logger.error(f"Unsplash API error: {e}")
            return []

    async def get_details(self, image_id: str) -> Optional[ImageResult]:
        """Get details for a specific Unsplash image."""
        if not self.session:
            raise RuntimeError(
                "Provider must be used within async context manager"
            )

        # Extract ID from our prefixed ID
        unsplash_id = image_id.replace("unsplash_", "")
        url = f"https://api.unsplash.com/photos/{unsplash_id}"
        headers = {"Authorization": f"Client-ID {self.api_key}"}

        try:
            # Use pycurl to make the request
            buffer = io.BytesIO()
            c = pycurl.Curl()
            
            c.setopt(pycurl.URL, url)
            c.setopt(pycurl.WRITEDATA, buffer)
            header_list = [f"{k}: {v}" for k, v in headers.items()]
            c.setopt(pycurl.HTTPHEADER, header_list)
            c.perform()
            
            # Check status code
            status_code = c.getinfo(pycurl.HTTP_CODE)
            if status_code != 200:
                logger.error(f"Unsplash API error: HTTP status {status_code}")
                return None
                
            c.close()
            
            # Parse JSON response
            response_data = buffer.getvalue().decode('utf-8')
            photo = json.loads(response_data)

            attribution_url = (
                f"https://unsplash.com/photos/{photo['id']}"
            )

            return ImageResult(
                id=f"unsplash_{photo['id']}",
                title=(photo.get("description") or
                       photo.get("alt_description") or
                       f"Photo by {photo['user']['name']}"),
                description=photo.get("description", ""),
                url=photo["urls"]["full"],
                thumbnail=photo["urls"]["regular"],
                width=photo["width"],
                height=photo["height"],
                photographer=photo["user"]["name"],
                photographer_url=photo["user"]["links"]["html"],
                source="Unsplash",
                license="Free to use under Unsplash License",
                attribution_url=attribution_url,
                tags=[tag["title"] for tag in photo.get("tags", [])]
            )
        except pycurl.error as e:
            logger.error(f"Unsplash API error: {e}")
            return None


class StockImageManager:
    """Manages multiple stock image providers and handles searches."""

    def __init__(self):
        """Initialize manager with configured providers."""
        self.providers: Dict[str, StockImageProvider] = {}

        # Check if attribution links are enabled
        attribution_links = (
            os.getenv("ENABLE_ATTRIBUTION_LINKS", "false").lower() == "true"
        )
        self.enable_attribution = attribution_links

        # Initialize Pexels if API key is available
        pexels_key = os.getenv("PEXELS_API_KEY")
        if pexels_key:
            self.providers["pexels"] = PexelsProvider(pexels_key)

        # Initialize Unsplash if API key is available
        unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY")
        if unsplash_key:
            self.providers["unsplash"] = UnsplashProvider(unsplash_key)

    async def search(self, query: str, providers: Optional[List[str]] = None,
                     per_page: int = 20, page: int = 1, sort: str = "relevant",
                     include_attribution: Optional[bool] = None,
                     **kwargs) -> Dict[str, Any]:
        """
        Search for images across specified providers.

        Args:
            query: Search query string
            providers: List of provider names to search
                      (defaults to all available)
            per_page: Number of results per page
            page: Page number
            sort: Sort order (relevant, latest, popular)
            **kwargs: Additional provider-specific parameters

        Returns:
            Dictionary with search results and metadata

        Note:
            If ENABLE_ATTRIBUTION_LINKS=true is set in the environment,
            results will include attribution URLs for proper crediting.
        """
        if not self.providers:
            error_msg = (
                "No image providers are configured. "
                "Please set at least one API key:\n"
                "- PEXELS_API_KEY for Pexels\n"
                "- UNSPLASH_ACCESS_KEY for Unsplash"
            )
            return {"error": error_msg}

        # Use all available providers if none specified
        if providers is None:
            providers = list(self.providers.keys())

        # Filter to only available providers
        available_providers = [
            p for p in providers if p in self.providers
        ]

        if not available_providers:
            return {
                "error": (
                    f"No available providers from: {', '.join(providers)}. "
                    "Please check your configuration."
                )
            }

        # Determine if attribution links should be included
        # Priority: 1) Explicit parameter, 2) Environment variable setting
        show_attribution = include_attribution if include_attribution is not None else self.enable_attribution

        results = {}
        for provider_name in available_providers:
            try:
                provider = self.providers[provider_name]
                async with provider:
                    provider_results = await provider.search(
                        query, per_page, page
                    )

                    # If attribution is disabled, set attribution_url
                    # to None for each result
                    if not show_attribution:
                        for result in provider_results:
                            result.attribution_url = None

                    results[provider_name] = provider_results
            except Exception as e:
                logger.error(f"Error searching {provider_name}: {e}")
                results[provider_name] = []

        return {
            "query": query,
            "page": page,
            "per_page": per_page,
            "providers": available_providers,
            "results": results
        }

    async def get_image_details(
            self, image_id: str, include_attribution: Optional[bool] = None) -> Dict[str, Any]:  # noqa: E501
        """
        Get detailed information about a specific image.

        Args:
            image_id: Provider-prefixed image ID
                     (e.g., "pexels_12345")

        Returns:
            Dictionary with image details or error
        """
        # Extract provider from ID
        provider_name = None
        for prefix in ["pexels_", "unsplash_"]:
            if image_id.startswith(prefix):
                provider_name = prefix.rstrip("_")

        # Determine if attribution links should be included
        # Priority: 1) Explicit parameter, 2) Environment variable setting
        show_attribution = include_attribution if include_attribution is not None else self.enable_attribution

        try:
            provider_name, provider_id = image_id.split("_", 1)

            if provider_name not in self.providers:
                return {"error": f"Unknown provider: {provider_name}"}

            provider = self.providers[provider_name]
            async with provider:
                result = await provider.get_details(provider_id)
                if result:
                    # If attribution is disabled, set attribution_url to None
                    if not show_attribution:
                        result.attribution_url = None
                    return asdict(result)
                return {"error": "Image not found"}

        except Exception as e:
            logger.error(f"Error getting image details: {e}")
            return {"error": str(e)}

    async def download_image(self,
                             image_id: str,
                             size: str = "original",
                             output_path: Optional[str] = None) -> Dict[str,
                                                                        Any]:
        """
        Download an image to local storage or return base64 encoded data.

        Args:
            image_id: Image ID in format provider_id (e.g., pexels_123456)
            size: Image size variant to download
                 Options: thumbnail, small, medium, large, original
            output_path: Optional path to save the image locally

        Returns:
            Dictionary with download information or error
        """
        # Validate size parameter
        valid_sizes = ["thumbnail", "small", "medium", "large", "original"]
        if size not in valid_sizes:
            return {
                "error": (f"Invalid size: {size}. Valid options: "
                          f"{', '.join(valid_sizes)}")
            }

        # Get image details first to obtain URLs
        image_details = await self.get_image_details(image_id)
        if "error" in image_details:
            return image_details

        # Determine which URL to use based on size
        image_url = None
        if "pexels_" in image_id:
            # Map size to Pexels URL
            if size == "thumbnail":
                image_url = image_details.get("thumbnail")
            elif size == "small":
                # Pexels doesn't have small
                image_url = image_details.get("thumbnail")
            elif size == "medium":
                # This is medium/large in Pexels
                image_url = image_details.get("url")
            elif size == "large":
                # This is medium/large in Pexels
                image_url = image_details.get("url")
            else:  # original
                # For Pexels, we need to modify the URL to get original size
                url = image_details.get("url", "")
                # Remove size constraints
                image_url = url.replace("?h=650&w=940", "")
        elif "unsplash_" in image_id:
            # Map size to Unsplash URL
            if size == "thumbnail":
                image_url = image_details.get("thumbnail")
            elif size == "small":
                # Use thumbnail for small
                image_url = image_details.get("thumbnail")
            elif size == "medium":
                # This is regular size in Unsplash
                image_url = image_details.get("url")
            elif size == "large":
                # This is regular size in Unsplash
                image_url = image_details.get("url")
            else:  # original
                # For Unsplash, the full URL is already in the details
                image_url = image_details.get("url")

        if not image_url:
            return {"error": "Could not determine image URL for download"}

        try:
            logger.info(f"Stocky MCP server CWD at download: {os.getcwd()}")
            # Use pycurl to download the image
            buffer = io.BytesIO()
            c = pycurl.Curl()
            c.setopt(c.URL, image_url)
            c.setopt(c.WRITEDATA, buffer)
            c.setopt(c.FOLLOWLOCATION, True)
            c.perform()

            # Get the content type and status code
            status_code = c.getinfo(pycurl.HTTP_CODE)
            content_type = c.getinfo(pycurl.CONTENT_TYPE) or "image/jpeg"
            c.close()

            if status_code != 200:
                return {
                    "error": f"Failed to download image: HTTP status {status_code}"}  # noqa: E501

            # Get the image data
            image_data = buffer.getvalue()

            # Get file extension from content type
            extension = content_type.split("/")[-1]
            if extension not in ["jpeg", "jpg", "png", "gif", "webp"]:
                extension = "jpg"  # Default to jpg if unknown

            # If output path is provided, save the image to disk
            if output_path:
                # Create directory if it doesn't exist
                output_path_obj = Path(output_path)
                output_path_obj.parent.mkdir(parents=True, exist_ok=True)

                # If no extension in output_path, add it
                if not output_path_obj.suffix:
                    output_path = f"{output_path}.{extension}"

                # Write the image to disk
                abs_path = str(Path(output_path).resolve())
                logger.info(f"Saving image to: {abs_path}")
                with open(abs_path, "wb") as f:
                    f.write(image_data)

                return {
                    "success": True,
                    "message": f"Image downloaded successfully to {abs_path}",  # noqa: E501
                    "path": abs_path,
                    "size": len(image_data),
                    "content_type": content_type}
            else:
                # Return base64 encoded image data
                encoded_data = base64.b64encode(image_data).decode("utf-8")
                return {
                    "success": True,
                    "message": "Image data retrieved successfully",
                    "data": encoded_data,
                    "size": len(image_data),
                    "content_type": content_type,
                    "encoding": "base64"
                }
        except pycurl.error as e:
            logger.error(f"Error downloading image: {e}")
            return {"error": f"Failed to download image: {str(e)}"}
        except IOError as e:
            logger.error(f"Error saving image to disk: {e}")
            return {"error": f"Failed to save image: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error during image download: {e}")
            return {"error": f"Unexpected error: {str(e)}"}


class StockyServer:
    """Main MCP server for stock image searching."""

    def __init__(self):
        self.mcp = FastMCP("stocky")
        self.manager = StockImageManager()
        self._setup_tools()
        self._setup_resources()

    def _setup_tools(self):
        """Set up MCP tools."""

        @self.mcp.tool("search_stock_images")
        async def search_stock_images(
            query: str,
            providers: Optional[List[str]] = None,
            per_page: int = 20,
            page: int = 1,
            sort_by: str = "relevant",
            include_attribution: Optional[bool] = None
        ) -> Dict[str, Any]:
            """
            Search for royalty-free stock images across multiple providers.

            Args:
                query: Search query string
                providers: List of specific providers to search
                per_page: Number of results per page
                page: Page number for pagination
                sort_by: Sort order ('relevant', 'newest')
                include_attribution: Whether to include attribution links
                    (defaults to value from ENABLE_ATTRIBUTION_LINKS env var)

            Returns:
                Search results with metadata
            """
            if per_page > 50:
                per_page = 50

            if providers is None:
                providers = list(self.manager.providers.keys())

            all_results = []

            # Pass the include_attribution parameter to the manager's search
            # method
            results_dict = await self.manager.search(
                query, providers, per_page, page, sort_by, include_attribution)

            # Convert results to the expected format
            if "results" in results_dict:
                for provider, images in results_dict["results"].items():
                    for image in images:
                        all_results.append(asdict(image))

            return {
                "results": all_results,
                "total_results": len(all_results),
                "query": query,
                "page": page,
                "per_page": per_page
            }

        @self.mcp.tool()
        async def get_image_details(
                image_id: str, include_attribution: Optional[bool] = None) -> Optional[Dict[str, Any]]:  # noqa: E501
            """
            Get detailed information about a specific image.

            Args:
                image_id: Provider-prefixed image ID
                          (e.g., 'pexels_12345')
                include_attribution: Whether to include attribution links
                    (defaults to value from ENABLE_ATTRIBUTION_LINKS env var)

            Returns:
                Detailed image information or None if not found
            """
            return await self.manager.get_image_details(image_id, include_attribution)  # noqa: E501

        @self.mcp.tool()
        async def download_image(image_id: str,
                                 size: str = "original",
                                 output_path: Optional[str] = None) -> Dict[str,  # noqa: E501
                                                                            Any]:  # noqa: E501
            """
            Download an image to local storage or return base64 encoded data.

            Args:
                image_id: Image ID in format provider_id (e.g., pexels_123456)
                size: Image size variant to download
                     Options: thumbnail, small, medium, large, original
                output_path: Optional path to save the image locally.
                    NOTE: If a relative path is provided, it will be resolved
                    from the Stocky MCP server's current working directory,
                    which may not be the project directory. To ensure the file
                    is saved in a specific location, use an absolute path
                    (e.g., /home/matt/Dev/stocky/downloads/image.jpg).

            Returns:
                Path to downloaded file or base64 data

            Example:
                download_image("pexels_123456", size="medium", output_path="/absolute/path/to/save.jpg")
            """
            return await self.manager.download_image(image_id, size, output_path)  # noqa: E501

    def _setup_resources(self):
        """Set up MCP resources."""

        @self.mcp.resource("stock-images://help")
        async def help_resource() -> str:
            """Provide help documentation for the Stocky MCP server."""
            return """
# Stocky MCP Server Help

Welcome to Stocky! This MCP server helps you search for beautiful
royalty-free stock images.

## Available Tools

### search_stock_images
Search for stock images across multiple providers.

Parameters:
- query (required): Your search terms
- providers (optional): List of providers to search
  ["pexels", "unsplash"]
- per_page (optional): Results per page (max 50)
- page (optional): Page number for pagination
- sort_by (optional): Sort results by 'relevance' or 'newest'

Example:
```
search_stock_images("sunset beach", per_page=10)
```

### get_image_details
Get detailed information about a specific image.

Parameters:
- image_id (required): Image ID in format 'provider_id'
  (e.g., 'pexels_123456')

Example:
```
get_image_details("unsplash_abc123")
```

### download_image
Download an image to local storage or get base64 encoded data.

Parameters:
- image_id (required): Image ID in format 'provider_id'
  (e.g., 'pexels_123456')
- size (optional): Image size variant to download
  Options: thumbnail, small, medium, large, original
  Default: original
- output_path (optional): Path to save the image locally
  If not provided, returns base64 encoded image data

Example:
```
download_image("pexels_123456", size="medium", output_path="/path/to/save.jpg")
```

## Providers

1. **Pexels** - High-quality stock photos
   - API Key: PEXELS_API_KEY
   - License: Free to use

2. **Unsplash** - Beautiful, free images
   - API Key: UNSPLASH_ACCESS_KEY
   - License: Unsplash License


   - License: Free for commercial use, no attribution required

## Setup

1. Get API keys from:
   - Pexels: https://www.pexels.com/api/
   - Unsplash: https://unsplash.com/developers


2. Set environment variables:
   ```bash
   export PEXELS_API_KEY="your_key"
   export UNSPLASH_ACCESS_KEY="your_key"

   ```

3. Run the server:
   ```bash
   python stocky_mcp.py
   ```

## Tips

- Use specific search terms for better results
- Check the license information for each image
- Use pagination for browsing large result sets
- Different providers may return different types of images

Happy searching! 📸
"""

    async def run(self):
        """Run the MCP server."""
        logger.info("Starting Stocky MCP server...")
        await self.mcp.run()


def main():
    """Main entry point for the MCP server."""
    server = StockyServer()
    server.mcp.run()


if __name__ == "__main__":
    main()
