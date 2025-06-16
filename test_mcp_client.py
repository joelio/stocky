#!/usr/bin/env python3
"""
Test client for Stocky MCP server.
This script tests the functionality of the Stocky MCP server by making requests to it.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

# Import the correct client classes
from mcp.client.session import ClientSession
from mcp.types import Tool, Resource


async def start_server_process():
    """Start the MCP server process in the background."""
    # This is just a simulation since we already have a server running
    print("Note: Using existing MCP server process")
    return None  # We're not actually starting a new process


async def test_search_images():
    """Test the search_stock_images tool."""
    print("Testing search_stock_images tool...")
    
    # Create a client session for the local MCP server
    session = ClientSession("stocky", "http://localhost:8080")
    await session.initialize()
    
    try:
        # Get available tools
        tools = await session.list_tools()
        print(f"Available tools: {[tool.name for tool in tools]}")
        
        # Test search with default parameters
        print("\nSearching for 'mountain landscape'...")
        result = await session.call_tool(
            "search_stock_images", 
            {"query": "mountain landscape"}
        )
        
        # Print the number of results and first result details
        if isinstance(result, list):
            print(f"Found {len(result)} images")
            if result:
                first_image = result[0]
                print("\nFirst image details:")
                print(f"ID: {first_image.get('id')}")
                print(f"Title: {first_image.get('title')}")
                print(f"Source: {first_image.get('source')}")
                print(f"URL: {first_image.get('url')}")
        else:
            print(f"Error: {result}")
    finally:
        await session.shutdown()


async def test_get_image_details():
    """Test the get_image_details tool."""
    print("\nTesting get_image_details tool...")
    
    # Create a client session for the local MCP server
    session = ClientSession("stocky", "http://localhost:8080")
    await session.initialize()
    
    try:
        # First search to get an image ID
        search_result = await session.call_tool(
            "search_stock_images", 
            {"query": "sunset", "per_page": 1}
        )
        
        if isinstance(search_result, list) and search_result:
            image_id = search_result[0].get('id')
            print(f"Getting details for image ID: {image_id}")
            
            # Get details for the first image
            details = await session.call_tool(
                "get_image_details", 
                {"image_id": image_id}
            )
            
            print("\nImage details:")
            print(json.dumps(details, indent=2))
        else:
            print("No images found to test get_image_details")
    finally:
        await session.shutdown()


async def test_help_resource():
    """Test the help resource."""
    print("\nTesting help resource...")
    
    # Create a client session for the local MCP server
    session = ClientSession("stocky", "http://localhost:8080")
    await session.initialize()
    
    try:
        # List available resources
        resources = await session.list_resources()
        print(f"Available resources: {[r.uri for r in resources]}")
        
        # Get the help resource
        help_text = await session.read_resource("stock-images://help")
        print(f"Help resource retrieved: {len(help_text)} characters")
        print("\nFirst 200 characters of help text:")
        print(help_text[:200] + "...")
    finally:
        await session.shutdown()


async def main():
    """Run all tests."""
    print("Starting Stocky MCP client tests...\n")
    
    # Start the server process (in this case, we're using an existing one)
    server_process = await start_server_process()
    
    try:
        # Run the tests
        await test_search_images()
        await test_get_image_details()
        await test_help_resource()
        print("\nAll tests completed!")
    except Exception as e:
        print(f"\nError during tests: {e}")
    finally:
        # We're not terminating the server since we didn't start it
        pass


if __name__ == "__main__":
    asyncio.run(main())
