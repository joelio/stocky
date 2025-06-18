#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Test script for Stocky MCP Server."""

from stocky_mcp import (
    PexelsProvider,
    UnsplashProvider,
)
import os
import sys
import asyncio
from dotenv import load_dotenv

# Add the parent directory to sys.path to import stocky_mcp
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class StockyTests:
    """Test suite for Stocky MCP Server."""

    def __init__(self):
        """Initialize the test suite."""
        self.results = {}
        self.passed = 0
        self.failed = 0
        self.failed_tests = []

    def add_result(
            self,
            test_name: str,
            passed: bool,
            message: str = "") -> None:
        """Add a test result."""
        self.results[test_name] = (passed, message)
        if passed:
            self.passed += 1
            print(f"✅ PASS: {test_name}")
        else:
            self.failed += 1
            self.failed_tests.append((test_name, message))
            print(f"❌ FAIL: {test_name}")
            if message:
                print(f"   Error: {message}")

    async def test_env_vars(self) -> None:
        """Test that environment variables are loaded."""
        print("\n🔧 Testing Environment Variables...")

        # Load environment variables
        load_dotenv()

        # Check for required API keys
        env_vars = {
            "PEXELS_API_KEY": "Pexels API key",
            "UNSPLASH_ACCESS_KEY": "Unsplash API key",
        }

        for var, name in env_vars.items():
            if os.getenv(var):
                self.add_result(f"{name} present", True)
            else:
                self.add_result(
                    f"{name} present",
                    False,
                    f"Environment variable {var} not found")

    async def test_pexels_connection(self) -> None:
        """Test connection to Pexels API."""
        print("\n📷 Testing Pexels API...")

        pexels_key = os.getenv("PEXELS_API_KEY")
        if not pexels_key:
            self.add_result(
                "Pexels API connection",
                False,
                "API key not found")
            return

        try:
            async with PexelsProvider(pexels_key) as provider:
                # Test search functionality
                results = await provider.search("nature", per_page=1)
                if results:
                    self.add_result(
                        "Pexels API connection", True, f"Found {len(results)} result(s)")

                    # Test getting details
                    if results[0].id:
                        # Extract provider_id from the id (format:
                        # pexels_12345)
                        provider_id = (
                            results[0].id.split('_')[1]
                            if '_' in results[0].id
                            else results[0].id
                        )
                        details = await provider.get_details(provider_id)
                        if details:
                            self.add_result(
                                "Pexels get_details",
                                True,
                                "Successfully retrieved image details"
                            )
                        else:
                            self.add_result(
                                "Pexels get_details",
                                False,
                                "Could not retrieve image details"
                            )
                else:
                    self.add_result(
                        "Pexels API connection", False, "No results found"
                    )
        except ValueError as e:
            self.add_result("Pexels API connection", False, str(e))
        except Exception as e:
            self.add_result(
                "Pexels API connection", False, f"Unexpected error: {str(e)}"
            )

    async def test_unsplash_connection(self) -> None:
        """Test connection to Unsplash API."""
        print("\n🌅 Testing Unsplash API...")

        unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY")
        if not unsplash_key:
            self.add_result(
                "Unsplash API connection",
                False,
                "API key not found")
            return

        try:
            async with UnsplashProvider(unsplash_key) as provider:
                # Test search functionality
                results = await provider.search("nature", per_page=1)
                if results:
                    self.add_result(
                        "Unsplash API connection", True, f"Found {
                            len(results)} result(s)")

                    # Test getting details
                    if results[0].id:
                        # Extract provider_id from the id (format:
                        # unsplash_12345)
                        provider_id = (
                            results[0].id.split('_')[1]
                            if '_' in results[0].id
                            else results[0].id
                        )
                        details = await provider.get_details(provider_id)
                        if details:
                            self.add_result(
                                "Unsplash get_details",
                                True,
                                "Successfully retrieved image details"
                            )
                        else:
                            self.add_result(
                                "Unsplash get_details",
                                False,
                                "Could not retrieve image details"
                            )
                else:
                    self.add_result(
                        "Unsplash API connection", False, "No results found"
                    )
        except ValueError as e:
            self.add_result("Unsplash API connection", False, str(e))
        except Exception as e:
            self.add_result(
                "Unsplash API connection", False, f"Unexpected error: {str(e)}"
            )

    async def test_search_functionality(self) -> None:
        """Test search functionality across all providers."""
        print("\n🔍 Testing Search Functionality...")

        # Add available providers
        providers_to_test = []
        pexels_key = os.getenv("PEXELS_API_KEY")
        unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY")

        if pexels_key:
            providers_to_test.append(("Pexels", PexelsProvider, pexels_key))
        if unsplash_key:
            providers_to_test.append(
                ("Unsplash", UnsplashProvider, unsplash_key))

        test_queries = [
            "nature landscape",
            "technology computer",
            "food cooking"]

        for query in test_queries:
            print(f"\n  Testing query: '{query}'")
            for provider_name, provider_class, api_key in providers_to_test:
                try:
                    async with provider_class(api_key) as provider:
                        results = await provider.search(query, per_page=3)
                        if results:
                            self.add_result(
                                f"{provider_name} search '{query}'",
                                True,
                                f"Found {len(results)} results"
                            )

                            # Validate result structure
                            result = results[0]
                            required_attrs = [
                                "id",
                                "title",
                                "url",
                                "thumbnail",
                                "width",
                                "height"
                            ]
                            missing_attrs = []
                            for attr in required_attrs:
                                if not hasattr(result, attr):
                                    missing_attrs.append(attr)

                            if not missing_attrs:
                                self.add_result(
                                    f"{provider_name} result validation", True)
                            else:
                                self.add_result(
                                    f"{provider_name} result validation",
                                    False,
                                    f"Missing attributes: "
                                    f"{', '.join(missing_attrs)}"
                                )
                        else:
                            self.add_result(
                                f"{provider_name} search '{query}'",
                                False,
                                "No results found"
                            )
                except Exception as e:
                    self.add_result(
                        f"{provider_name} search '{query}'",
                        False,
                        f"Error: {str(e)}"
                    )

    async def test_error_handling(self) -> None:
        """Test error handling."""
        print("\n🛡️ Testing Error Handling...")

        # Test invalid image ID format
        print("  Testing invalid image ID format...")
        try:
            # Use a provider directly instead of server
            pexels_key = os.getenv("PEXELS_API_KEY") or ""
            async with PexelsProvider(pexels_key) as provider:
                # Force an exception by using an invalid ID format
                result = await provider.get_details("invalid_format")
                # If we get here without an exception, it's a failure
                if result is None:
                    # Some providers might return None for invalid IDs instead
                    # of raising
                    self.add_result(
                        "Invalid image ID handling",
                        True,
                        "Correctly returned None for invalid ID"
                    )
                else:
                    self.add_result(
                        "Invalid image ID handling",
                        False,
                        "Should have raised an exception or returned None"
                    )
        except Exception as e:
            self.add_result(
                "Invalid image ID handling",
                True,
                f"Correctly handled error: {str(e)}"
            )

    async def run_all_tests(self) -> None:
        """Run all tests."""
        await self.test_env_vars()
        await self.test_pexels_connection()
        await self.test_unsplash_connection()
        await self.test_search_functionality()
        await self.test_error_handling()

        # Print summary
        print("\n" + "=" * 50)
        print("📊 TEST SUMMARY")
        print("=" * 50 + "\n")

        print(f"Total tests: {self.passed + self.failed}")
        print(f"✅ Passed: {self.passed}")
        print(f"❌ Failed: {self.failed}")

        if self.failed > 0:
            print("\n❌ Failed tests:")
            for test_name, message in self.failed_tests:
                print(f"  - {test_name}: {message}")

        print("\n" + "=" * 50 + "\n")

        if self.failed == 0:
            print("✨ All tests passed! Stocky is ready to use.")
        else:
            print("⚠️  Some tests failed. Please check the errors above.")


async def main():
    """Run the tests."""
    print("🧪 Starting Stocky MCP Server Tests")
    print("=" * 50)

    tests = StockyTests()
    await tests.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
