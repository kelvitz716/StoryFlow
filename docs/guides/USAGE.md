# Usage Guide

## Telegram Bot

Once the bot is running, interact with it on Telegram.

### Basic Commands

| Command | Description |
|:---|:---|
| `/start` | Shows the main menu with interactive buttons. |
| `/help` | Displays the help message and usage instructions. |
| `/upload_cookies` | Upload a `cookies.txt` file for authentication. |
| `/my_cookies` | List currently active cookies. |
| `/delete_cookies` | Select cookies to delete. |

### Downloading Media

Simply **send a link** to the bot. It supports:

- **Instagram**: Reels, Stories, Posts.
  - *Note: Stories usually require cookies.*
- **Snapchat**: Public Stories.
- **TikTok**: Videos (Watermark-free).
- **Facebook**: Public Reels/Videos.
- **Twitter/X**: Videos/GIFs.

The bot will:
1.  Analyze the link.
2.  Download the content.
3.  Upload it back to you.
4.  Delete the temporary file from the server.

### Authentication (Cookies)

Some content (especially Instagram Stories or age-gated videos) requires login.

1.  **Export Cookies**: Use a browser extension like "Get cookies.txt LOCALLY" (Chrome/Firefox) to export cookies from Instagram or Facebook while logged in.
2.  **Upload to Bot**:
    - Send `/upload_cookies`.
    - Select the platform button (Instagram or Facebook).
    - Send the `.txt` file when prompted.
3.  **Automatic Usage**: The bot will automatically use these cookies for future requests.

### Large Files

- **Standard**: Files up to 50MB are sent normally.
- **Large**: Files > 50MB (up to 2GB) are sent via MTProto.
  - You will see a "📤 Uploading: XX%" progress log in the bot console (and a "Sending..." status in Telegram).

## CLI Mode

You can also run StoryFlow as a command-line tool for testing.

```bash
# Set MODE=cli in .env
python storyflow.py
```

It will prompt for a URL and try to download it to the `./downloads` folder.
