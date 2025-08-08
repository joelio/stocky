#!/usr/bin/env python3
"""
Demo script for Stocky MCP Server.

This script demonstrates the usage of Stocky's functionality through direct API calls.
Note: In production, Stocky would be used through the MCP protocol.
"""

import asyncio
import json
import os
import sys
from typing import List, Dict, Any
from dotenv import load_dotenv

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from stocky_mcp import PexelsProvider, UnsplashProvider, ImageResult
except ImportError:
    print("Error: Could not import stocky_mcp. Make sure it's in the same directory.")
    sys.exit(1)


class StockyDemo:
    """Demo class for showcasing Stocky functionality."""

    def __init__(self):
        load_dotenv()
        self.providers = {}

        # Initialize providers with API keys from environment variables
        pexels_key = os.getenv("PEXELS_API_KEY")
        if pexels_key:
            # We know pexels_key is not None here due to the if check
            self.providers["pexels"] = lambda: PexelsProvider(pexels_key or "")

        unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY")
        if unsplash_key:
            # We know unsplash_key is not None here due to the if check
            self.providers["unsplash"] = lambda: UnsplashProvider(unsplash_key or "")



    def print_header(self, text: str):
        """Print a formatted header."""
        print(f"\n{'=' * 60}")
        print(f"📸 {text}")
        print('=' * 60)

    def print_image_result(self, image: ImageResult, detailed: bool = False):
        """Print a formatted image result."""
        print(f"\n🖼️  {image.title or 'Untitled'}")
        print(f"   ID: {image.id}")
        print(f"   📷 By: {image.photographer}")
        print(f"   📐 Size: {image.width}x{image.height}")
        print(f"   🔗 URL: {image.url}")

        if detailed:
            print(f"   📝 Description: {image.description or 'No description'}")
            print(f"   🌐 Source: {image.source}")
            print(f"   📄 License: {image.license}")
            if image.photographer_url:
                print(f"   👤 Photographer URL: {image.photographer_url}")

    async def demo_search_all_providers(
            self, query: str = "mountain landscape"):
        """Demo searching across all available providers."""
        self.print_header(f"Searching all providers for: '{query}'")

        results_by_provider = {}

        for provider_name, provider_class in self.providers.items():
            try:
                print(f"\n🔍 Searching {provider_name.capitalize()}...")
                provider_factory = provider_class
                async with provider_factory() as provider:
                    results = await provider.search(query, per_page=3)
                    results_by_provider[provider_name] = results

                    if results:
                        print(f"   ✅ Found {len(results)} images")
                        for i, image in enumerate(results, 1):
                            print(f"   {i}. {image.title or 'Untitled'} (ID: {image.id})")
                    else:
                        print(f"   ⚠️  No results found")

            except ValueError as e:
                print(f"   ❌ Error: {e}")
                print(
                    (f"      Please set "
                     f"{provider_name.upper()}_API_KEY in your .env file")
            except Exception as e:
                print(f"   ❌ Unexpected error: {e}")

        return results_by_provider

    async def demo_search_specific_provider(
            self,
            provider_name: str = "pexels",
            query: str = "coffee"):
        """Demo searching a specific provider."""
        self.print_header(
            f"Searching {
                provider_name.capitalize()} for: '{query}'")

        if provider_name not in self.providers:
            print(f"❌ Unknown provider: {provider_name}")
            print(
                f"   Available providers: {
                    ', '.join(
                        self.providers.keys())}")
            return []

        try:
            provider_factory = self.providers[provider_name]
            async with provider_factory() as provider:
                results = await provider.search(query, per_page=5, page=1)

                if results:
                    print(f"\nFound {len(results)} images:")
                    for image in results:
                        self.print_image_result(image)
                else:
                    print("No results found")

                return results

        except ValueError as e:
            print(f"Error: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error: {e}")
            return []

    async def demo_get_image_details(self, provider_name: str, image_id: str):
        """Demo getting detailed information about a specific image."""
        self.print_header(
            f"Getting details for {provider_name} image: {image_id}")

        if provider_name not in self.providers:
            print(f"❌ Unknown provider: {provider_name}")
            return None

        try:
            provider_factory = self.providers[provider_name]
            async with provider_factory() as provider:
                details = await provider.get_details(image_id)

                if details:
                    print("\n✅ Image details retrieved:")
                    self.print_image_result(details, detailed=True)
                else:
                    print("❌ Image not found")

                return details

        except Exception as e:
            print(f"❌ Error: {e}")
            return None

    async def demo_pagination(
            self,
            provider_name: str = "pexels",
            query: str = "nature"):
        """Demo pagination functionality."""
        self.print_header(
            f"Demonstrating pagination with {
                provider_name.capitalize()}")

        if provider_name not in self.providers:
            print(f"❌ Unknown provider: {provider_name}")
            return

        try:
            provider_class = self.providers[provider_name]

            print(f"\n🔍 Searching for '{query}' with pagination...")

            for page in range(1, 4):  # Get first 3 pages
                print(f"\n📄 Page {page}:")

                async with provider_class() as provider:
                    results = await provider.search(query, per_page=5, page=page)

                    if results:
                        for i, image in enumerate(results, 1):
                            print(
                                f"   {(page - 1) * 5 + i}. {image.title or 'Untitled'} - {image.photographer}")
                    else:
                        print("   No more results")
                        break

        except ValueError as e:
            print(f"❌ Error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")

    async def demo_error_handling(self):
        """Demo error handling scenarios."""
        self.print_header("Demonstrating Error Handling")

        # Test with missing API key
        try:
            print("1️⃣ Testing missing API key scenario:")
            # Deliberately passing None to test error handling
            provider = PexelsProvider("")
            print("   This should have failed but didn't!")
        except ValueError as e:
            print(f"   Expected error: {e}")

        # Test with invalid API key
        try:
            print("2️⃣ Testing invalid API key scenario:")
            provider = PexelsProvider("invalid_key")
            async with provider:
                results = await provider.search("test")
                # If we get here without an exception but have no results,
                # that's expected
                if not results:
                    print(
                        "   ✅ Expected behavior: API returned no results with invalid key")
                else:
                    print("   ❌ This should have failed or returned no results!")
        except Exception as e:
            print(f"   ✅ Expected error: {e}")

        # Test invalid image ID
        print("\n2️⃣ Testing invalid image ID:")
        print("   In MCP context, this would return an error response")
        print("   Example: get_image_details('invalid_format_id')")
        print("   Expected: Error about invalid ID format")

    async def demo_json_output(self, default_query: str = "sunset"):
        """Demo JSON output format."""
        self.print_header("JSON Output Examples")

        # Provider-specific queries to avoid API issues
        provider_queries = {
            "pexels": "sunset",
            "unsplash": "nature"
        }

        success = False

        # Try each provider with its specific query
        for provider_name, provider_class in self.providers.items():
            query = provider_queries.get(provider_name, default_query)
            try:
                print(
                    f"\n🔍 Trying {
                        provider_name.capitalize()} with query: '{query}'")
                async with provider_class() as provider:
                    results = await provider.search(query, per_page=2)

                    if results:
                        print(
                            f"  ✅ Sample JSON output from {
                                provider_name.capitalize()}:")

                        # Convert to dict format (as would be returned by MCP)
                        json_result = {
                            "id": results[0].id,
                            "title": results[0].title,
                            "description": results[0].description,
                            "url": results[0].url,
                            "thumbnail": results[0].thumbnail,
                            "width": results[0].width,
                            "height": results[0].height,
                            "photographer": results[0].photographer,
                            "photographer_url": results[0].photographer_url,
                            "source": results[0].source,
                            "license": results[0].license
                        }

                        print(json.dumps(json_result, indent=2))
                        success = True
                    else:
                        print(f"  ⚠️ No results found for '{query}'")

            except Exception as e:
                print(f"  ❌ Error: {e}")

        if not success:
            print("\n❌ No providers available for JSON demo")


async def interactive_menu():
    """Run an interactive demo menu."""
    demo = StockyDemo()

    print("\n🎨 Welcome to Stocky Demo!")
    print("=" * 60)

    while True:
        print("\n📋 Demo Options:")
        print("1. Search all providers")
        print("2. Search specific provider")
        print("3. Get image details")
        print("4. Pagination demo")
        print("5. Error handling demo")
        print("6. JSON output example")
        print("7. Run all demos")
        print("0. Exit")

        choice = input("\nSelect option (0-7): ").strip()

        if choice == "0":
            print("\n👋 Thanks for trying Stocky!")
            break

        elif choice == "1":
            query = input(
                "Enter search query (default: 'mountain landscape'): ").strip()
            await demo.demo_search_all_providers(query or "mountain landscape")

        elif choice == "2":
            provider = input(
                "Enter provider (pexels/unsplash): ").strip().lower()
            query = input("Enter search query (default: 'coffee'): ").strip()
            results = await demo.demo_search_specific_provider(provider or "pexels", query or "coffee")

        elif choice == "3":
            print("\n💡 First, let's find an image to get details for...")
            provider = input(
                "Enter provider (pexels/unsplash): ").strip().lower() or "pexels"

            # Search for an image first
            results = await demo.demo_search_specific_provider(provider, "technology")
            if results and len(results) > 0:
                # Use the first result's ID
                image_id = results[0].provider_id
                await demo.demo_get_image_details(provider, image_id)
            else:
                print("❌ No images found to get details for")

        elif choice == "4":
            provider = input(
                "Enter provider (default: pexels): ").strip().lower()
            query = input("Enter search query (default: 'nature'): ").strip()
            await demo.demo_pagination(provider or "pexels", query or "nature")

        elif choice == "5":
            await demo.demo_error_handling()

        elif choice == "6":
            query = input("Enter search query (default: 'sunset'): ").strip()
            await demo.demo_json_output(query or "sunset")

        elif choice == "7":
            # Run all demos
            await demo.demo_search_all_providers()
            await demo.demo_search_specific_provider()
            await demo.demo_pagination()
            await demo.demo_error_handling()
            await demo.demo_json_output()

        else:
            print("❌ Invalid option. Please try again.")

        input("\nPress Enter to continue...")


async def automated_demo():
    """Run automated demo showcasing all features."""
    demo = StockyDemo()

    print("\n🎬 Running Automated Stocky Demo")
    print("=" * 60)

    # Demo 1: Search all providers
    await demo.demo_search_all_providers("ocean waves")

    # Demo 2: Search specific provider with more results
    await demo.demo_search_specific_provider("unsplash", "city skyline")

    # Demo 3: Pagination
    await demo.demo_pagination("pexels", "flowers")

    # Demo 4: Error handling
    await demo.demo_error_handling()

    # Demo 5: JSON output
    await demo.demo_json_output("technology")

    print("\n✨ Demo complete!")
    print("=" * 60)


async def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "--auto":
        await automated_demo()
    else:
        await interactive_menu()


if __name__ == "__main__":
    print("🚀 Stocky Demo Script")
    print("Run with --auto flag for automated demo")
    print("Or run without flags for interactive menu")

    asyncio.run(main())
