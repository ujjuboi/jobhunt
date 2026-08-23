# Job Board Adapters

This document explains how to use the different job board adapters in JobHunt, including the new LinkedIn and Indeed sources.

## Available Adapters

### 1. Greenhouse (API-based)
- **Source Type**: `greenhouse`
- **API Key Required**: Yes
- **Usage**: `get_source_adapter('greenhouse', api_key='your-key-here')`

### 2. Lever (API-based)
- **Source Type**: `lever`
- **API Key Required**: Yes
- **Usage**: `get_source_adapter('lever', api_key='your-key-here')`

### 3. Ashby (API-based)
- **Source Type**: `ashby`
- **API Key Required**: Yes
- **Usage**: `get_source_adapter('ashby', api_key='your-key-here')`

### 4. LinkedIn (Web Scraping)
- **Source Type**: `linkedin`
- **Authentication**: Browser login (no stored credentials)
- **Usage**: `get_source_adapter('linkedin')`
- **Via the UI**: on the Settings screen, enable `linkedin` and click **Login to LinkedIn**.
- **Setup**: install the browser first with `uv run playwright install chromium`.
- **Session**: signing in happens once in a visible (headful) browser — the user
  enters their credentials there — and the session cookie jar is saved to
  `cache/linkedin_session.json`. Later runs reuse it in headless mode.

> ⚠️ **Important**: LinkedIn scraping is against LinkedIn's Terms of Service. This implementation is provided for educational purposes only.
> 
> When using LinkedIn scraping:
> 1. You must comply with LinkedIn's robots.txt
> 2. Use rate limiting to avoid being blocked
> 3. Consider using LinkedIn's official API when available
> 4. Be aware that scraping may break if LinkedIn changes their UI

### 5. Indeed (Web Scraping)
- **Source Type**: `indeed`
- **API Key Required**: No
- **Usage**: `get_source_adapter('indeed')`
- **Setup**: install the browser first with `uv run playwright install chromium`.

> ⚠️ **Important**: Indeed scraping is against Indeed's Terms of Service. This implementation is provided for educational purposes only.
> 
> When using Indeed scraping:
> 1. You must comply with Indeed's robots.txt
> 2. Use rate limiting to avoid being blocked
> 3. Consider using Indeed's official API when available
> 4. Be aware that scraping may break if Indeed changes their UI