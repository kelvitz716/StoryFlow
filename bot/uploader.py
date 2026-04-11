"""Media upload logic for StoryFlow bot."""
import os
import logging
import asyncio
from typing import List, Optional
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.error import RetryAfter

async def batch_upload_media(update: Update, files: List[str], status_msg, mtproto_client=None) -> None:
    """
    Upload media files in batches using Telegram media groups.
    
    Supports >50MB files via MTProto client if configured.
    """
    total_files = len(files)
    batch_size = 10  # Telegram max for media groups
    batches = [files[i:i + batch_size] for i in range(0, len(files), batch_size)]
    
    uploaded_count = 0
    failed_count = 0
    
    for batch_idx, batch in enumerate(batches):
        batch_start = batch_idx * batch_size + 1
        batch_end = min((batch_idx + 1) * batch_size, total_files)
        
        # Check for large files in batch
        large_files = [f for f in batch if os.path.exists(f) and os.path.getsize(f) > 50 * 1024 * 1024]
        
        if large_files and mtproto_client and mtproto_client.is_connected:
            # Use MTProto for large files
            logging.info(f"📤 Batch {batch_idx+1} contains large files (>50MB). Using MTProto.")
            await status_msg.edit_text(f"🚀 *Uploading Large Files...*\n(Batch {batch_idx+1}/{len(batches)})", parse_mode='Markdown')
            
            for file_path in batch:
                if not os.path.exists(file_path):
                    continue
                
                success = await mtproto_client.upload_file(
                    chat_id=update.effective_chat.id,
                    file_path=file_path,
                    reply_to_message_id=update.effective_message.message_id
                )
                if success:
                    uploaded_count += 1
                else:
                    failed_count += 1
            continue

        # Normal upload for < 50MB
        media_group = []
        for file_path in batch:
            if not os.path.exists(file_path):
                continue
            
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png', '.webp'):
                media_group.append(InputMediaPhoto(media=open(file_path, 'rb')))
            elif ext in ('.mp4', '.mov', '.avi', '.mkv', '.webm'):
                media_group.append(InputMediaVideo(media=open(file_path, 'rb')))
        
        if not media_group:
            continue
            
        try:
            await status_msg.edit_text(f"🚀 *Uploading...*\n(Batch {batch_idx+1}/{len(batches)})", parse_mode='Markdown')
            await update.effective_message.reply_media_group(media=media_group)
            uploaded_count += len(media_group)
        except RetryAfter as e:
            logging.warning(f"⚠️ Rate limited. Waiting {e.retry_after}s...")
            await asyncio.sleep(e.retry_after)
            # Retry once
            try:
                await update.effective_message.reply_media_group(media=media_group)
                uploaded_count += len(media_group)
            except Exception as e2:
                logging.error(f"❌ Failed to upload batch after retry: {e2}")
                failed_count += len(media_group)
        except Exception as e:
            logging.error(f"❌ Failed to upload batch: {e}")
            failed_count += len(media_group)
        finally:
            # Close file handles (essential!)
            for media in media_group:
                if hasattr(media.media, 'close'):
                    media.media.close()

    if failed_count > 0:
        await status_msg.edit_text(f"✅ Delivered {uploaded_count} files.\n⚠️ {failed_count} files failed to upload (likely too large or invalid format).")
    else:
        await status_msg.delete()
