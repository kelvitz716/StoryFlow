"""Media upload logic for StoryFlow bot."""
import os
import logging
import asyncio
from typing import List, Optional
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.error import RetryAfter

async def safe_edit_text(message, text: str):
    """Safely edit a message, ignoring rate limits for secondary status updates."""
    try:
        await message.edit_text(text, parse_mode='Markdown')
    except RetryAfter as e:
        # Ignore rate limits for status updates to prioritize actual file delivery
        logging.warning(f"🤫 Status update throttled (waiting {e.retry_after}s), skipping.")
    except Exception as e:
        logging.debug(f"ℹ️ Status update failed: {e}")

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
        
        # Proactive cooling delay between batches to avoid rate limits
        if batch_idx > 0:
            await asyncio.sleep(1.5)

        # Check for large files in batch
        large_files = [f for f in batch if os.path.exists(f) and os.path.getsize(f) > 5 * 1024 * 1024]
        
        # MTProto Fallback: Use it if forced (large files) OR if we previously hit rate limits
        use_mtproto = bool(large_files and mtproto_client and mtproto_client.is_connected)
        
        if use_mtproto:
            logging.info(f"📤 Batch {batch_idx+1} using MTProto rescue.")
            await safe_edit_text(status_msg, f"🚀 *MTProto Delivery...*\n(Batch {batch_idx+1}/{len(batches)})")
            
            # Use MTProto Media Group
            success = await mtproto_client.send_media_group(
                chat_id=update.effective_chat.id,
                files=batch,
                reply_to_message_id=update.effective_message.message_id
            )
            
            if success:
                uploaded_count += len(batch)
            else:
                # Individual fallback
                for file_path in batch:
                    if await mtproto_client.upload_file(update.effective_chat.id, file_path, reply_to_message_id=update.effective_message.message_id):
                        uploaded_count += 1
                    else:
                        failed_count += 1
            continue

        # Normal upload for Bot API
        media_group = []
        for file_path in batch:
            if not os.path.exists(file_path): continue
            
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png', '.webp'):
                media_group.append(InputMediaPhoto(media=open(file_path, 'rb')))
            elif ext in ('.mp4', '.mov', '.avi', '.mkv', '.webm'):
                media_group.append(InputMediaVideo(media=open(file_path, 'rb')))
        
        if not media_group: continue
            
        # Recursive-style retry loop for Bot API
        attempts = 0
        max_attempts = 3
        while attempts < max_attempts:
            try:
                await safe_edit_text(status_msg, f"🚀 *Uploading...*\n(Batch {batch_idx+1}/{len(batches)})")
                await update.effective_message.reply_media_group(media=media_group)
                uploaded_count += len(media_group)
                break
            except RetryAfter as e:
                attempts += 1
                wait_time = e.retry_after + 1
                logging.warning(f"⚠️ Flood control! Waiting {wait_time}s (Attempt {attempts}/{max_attempts})...")
                
                # FALLBACK IMMEDIATELY to MTProto on first rate limit if available
                if mtproto_client and mtproto_client.is_connected:
                    logging.info("🔄 Bot API throttled. Switching to MTProto rescue immediately.")
                    await safe_edit_text(status_msg, f"🚀 *MTProto Rescue...*\n(Batch {batch_idx+1}/{len(batches)})")
                    success = await mtproto_client.send_media_group(
                        chat_id=update.effective_chat.id,
                        files=batch,
                        reply_to_message_id=update.effective_message.message_id
                    )
                    if success:
                        uploaded_count += len(media_group)
                        break
                
                # Otherwise wait and try again
                await safe_edit_text(status_msg, f"⏳ *Waiting...*\n({wait_time}s to resume)")
                await asyncio.sleep(wait_time)
            except Exception as e:
                logging.error(f"❌ Batch upload failed: {e}")
                failed_count += len(media_group)
                break
            finally:
                # Close file handles
                for media in media_group:
                    if hasattr(media.media, 'close'): media.media.close()
        else:
            # Reached max attempts
            failed_count += len(media_group)

    if failed_count > 0:
        await safe_edit_text(status_msg, 
            f"✅ Delivered {uploaded_count} files.\n"
            f"⚠️ {failed_count} files failed to upload."
        )
    else:
        try:
            await status_msg.delete()
        except:
            pass
