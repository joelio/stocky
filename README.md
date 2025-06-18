# <div align="center">![Stocky Logo](STOCKY.png)<br/>Stocky<br/>*Find beautiful royalty-free stock images* 📸</div>

<div align="center">

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://github.com/modelcontextprotocol)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

## ✨ Features

- 🔍 **Multi-Provider Search** - Search across Pexels and Unsplash simultaneously
- 📊 **Rich Metadata** - Get comprehensive image details including dimensions, photographer info, and licensing
- 📄 **Pagination Support** - Browse through large result sets with ease
- 🛡️ **Graceful Error Handling** - Robust error handling for API failures
- ⚡ **Async Performance** - Lightning-fast concurrent API calls
- 🎯 **Provider Flexibility** - Search specific providers or all at once

![Photography Example](images/photography-example1.jpg)

**Beautiful stock photography at your fingertips**  
Example image used for demonstration purposes

![Mountain Landscape](images/landscape-mountains.jpg)
*Stunning landscapes available through multiple providers*

Photo by [Simon Berger](https://unsplash.com/@simon_berger) on [Unsplash](https://unsplash.com/photos/twukN12EN7c)

## 🚀 Quick Start

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/stocky-mcp.git
cd stocky-mcp
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

### API Key Setup

You'll need free API keys from each provider:

1. **Pexels** 📷 - Get your key at [pexels.com/api](https://www.pexels.com/api/)
2. **Unsplash** 🌅 - Sign up at [unsplash.com/developers](https://unsplash.com/developers)


### API Key Configuration

You'll need to configure your API keys when setting up the MCP server. These keys are used to authenticate with the stock image providers.

### Running as an MCP Server

Stocky is designed to be run as an MCP (Model Context Protocol) server, not as a standalone application. It should be configured in your MCP client configuration.

## 🔧 MCP Client Configuration

Add Stocky to your MCP client configuration:

```json
{
  "mcpServers": {
    "stocky": {
      "command": "python",
      "args": ["/path/to/stocky_mcp.py"],
      "env": {
        "PEXELS_API_KEY": "your_pexels_key",
        "UNSPLASH_ACCESS_KEY": "your_unsplash_key",

      }
    }
  }
}
```

## 📖 Usage Examples

<div align="center">
<img src="images/photography-example2.jpg" alt="Stock Photography Example" width="600">
<p><em>Find the perfect image for your project</em></p>
</div>

### Searching for Images

Search across all providers:
```python
results = await search_stock_images("sunset beach")
```

Search specific providers:
```python
results = await search_stock_images(
    query="mountain landscape",
    providers=["pexels", "unsplash"],
    per_page=30,
    page=1
)
```

### Getting Image Details

```python
details = await get_image_details("unsplash_abc123xyz")
```

### Downloading Images

```python
# Download and save to disk
result = await download_image(
    image_id="pexels_123456", 
    size="medium", 
    output_path="/path/to/save.jpg"
)

# Get base64-encoded image data
result = await download_image(
    image_id="unsplash_abc123", 
    size="original"
)
```

## 🛠️ Tools Documentation

### `search_stock_images`

Search for royalty-free stock images across multiple providers.

**Parameters:**
- `query` (str, required) - Search terms for finding images
- `providers` (list, optional) - List of providers to search: `["pexels", "unsplash"]`
- `per_page` (int, optional) - Results per page, max 50 (default: 20)
- `page` (int, optional) - Page number for pagination (default: 1)
- `sort_by` (str, optional) - Sort results by "relevance" or "newest"

**Returns:** List of image results with metadata

### `get_image_details`

Get detailed information about a specific image.

**Parameters:**
- `image_id` (str, required) - Image ID in format `provider_id` (e.g., `pexels_123456`)

**Returns:** Detailed image information including full metadata

### `download_image`

Download an image to local storage or get base64 encoded data.

**Parameters:**
- `image_id` (str, required) - Image ID in format `provider_id` (e.g., `pexels_123456`)
- `size` (str, optional) - Image size variant to download (default: "original")
  - Options: thumbnail, small, medium, large, original
- `output_path` (str, optional) - Path to save the image locally
  - If not provided, returns base64 encoded image data

**Returns:** Dictionary with download information or error

## 📄 License Information

<div align="center">
<img src="images/photography-example3.jpg" alt="License Information" width="600">
<p><em>Royalty-free images for your creative projects</em></p>
</div>

All images returned by Stocky are free to use:

- **Pexels** ✅ - Free for commercial and personal use, no attribution required
- **Unsplash** ✅ - Free under the Unsplash License


Always check the specific license for each image before use in production.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 🙏 Acknowledgments

- Thanks to [Pexels](https://www.pexels.com) and [Unsplash](https://unsplash.com) for providing free APIs
- Built with the [Model Context Protocol](https://github.com/modelcontextprotocol)
- Created with ❤️ for the developer community

## 🐛 Troubleshooting

### Common Issues

**"API key not found" error**
- Ensure your `.env` file exists and contains valid API keys
- Check that environment variables are properly loaded
- Verify API key names match exactly (case-sensitive)

**No results returned**
- Try different search terms
- Check your internet connection
- Verify API keys are active and have not exceeded rate limits

**Installation issues**
- Ensure Python 3.8+ is installed
- Try creating a virtual environment: `python -m venv venv`
- Update pip: `pip install --upgrade pip`

### Rate Limiting

Each provider has different rate limits:
- **Pexels**: 200 requests per hour
- **Unsplash**: 50 requests per hour (demo), 5000 per hour (production)


---

<div align="center">
Made with 💜 by the Stocky Team
</div>
