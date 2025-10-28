# Caching Example

This demonstrates how the caching feature works when fetching from the Knack API.

## First Run (No Cache)

When you run the command for the first time with API credentials:

```bash
$ uv run knack-sleuth search-object object_12 --app-id YOUR_APP_ID --api-key YOUR_KEY
```

**What happens:**
1. No cache file exists
2. Fetches data from Knack API
3. Saves to `YOUR_APP_ID_app_metadata_202510281430.json` (timestamp varies)
4. Displays results

**Output:**
```
Fetching metadata from Knack API...
Cached metadata to YOUR_APP_ID_app_metadata_202510281430.json
╭─────────────────── Object Search Results ────────────────────╮
│ College/School (object_12)                                    │
╰───────────────────────── 4 fields ────────────────────────────╯
...
```

## Second Run (Within 24 Hours)

When you run the same command again within 24 hours:

```bash
$ uv run knack-sleuth search-object object_12
```

**What happens:**
1. Finds existing cache file
2. Checks age (e.g., 2.5 hours old)
3. Uses cached data (no API call!)
4. Displays results

**Output:**
```
Using cached data from YOUR_APP_ID_app_metadata_202510281430.json (age: 2.5h)
╭─────────────────── Object Search Results ────────────────────╮
│ College/School (object_12)                                    │
╰───────────────────────── 4 fields ────────────────────────────╯
...
```

## Force Refresh

To ignore the cache and fetch fresh data:

```bash
$ uv run knack-sleuth search-object object_12 --refresh
```

**What happens:**
1. Ignores existing cache files
2. Fetches fresh data from Knack API
3. Creates new cache file with current timestamp
4. Displays results

**Output:**
```
Forcing refresh from API...
Fetching metadata from Knack API...
Cached metadata to YOUR_APP_ID_app_metadata_202510281545.json
╭─────────────────── Object Search Results ────────────────────╮
│ College/School (object_12)                                    │
╰───────────────────────── 4 fields ────────────────────────────╯
...
```

## Cache Expiration (After 24 Hours)

If the cache file is older than 24 hours:

```bash
$ uv run knack-sleuth search-object object_12
```

**What happens:**
1. Finds existing cache file
2. Checks age (e.g., 25.3 hours old)
3. Cache is expired, fetches fresh data
4. Creates new cache file
5. Displays results

**Output:**
```
Fetching metadata from Knack API...
Cached metadata to YOUR_APP_ID_app_metadata_202510291415.json
╭─────────────────── Object Search Results ────────────────────╮
│ College/School (object_12)                                    │
╰───────────────────────── 4 fields ────────────────────────────╯
...
```

## Benefits

- **Speed**: Subsequent searches are instant (no API calls)
- **Cost**: Reduces API usage when doing multiple searches
- **Workflow**: Perfect for exploring and analyzing your app structure
- **Fresh Data**: Automatic refresh after 24 hours or manual with `--refresh`

## Clean Up Old Cache Files

Cache files accumulate over time. You can clean them up:

```bash
# Remove all cache files for a specific app
rm YOUR_APP_ID_app_metadata_*.json

# Remove all cache files older than 7 days
find . -name "*_app_metadata_*.json" -mtime +7 -delete
```
