"""Media upload logic for StoryFlow bot."""
import os
import logging
import asyncio
from typing import List, Optional
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.error import RetryAfter, NetworkError, TimedOut

import time

LAST_EDIT_TIMES = {}
EDIT_THROTTLE_SECONDS = 3.5

async def safe_edit_text(message, text: str):
    """Safely edit a message, throttling UI updates to avoid cascading rate limits."""
    current_time = time.time()
    msg_id = message.message_id
    
    # Lightweight Garbage Collection to prevent memory leaks
    if len(LAST_EDIT_TIMES) > 100:
        cutoff = current_time - 3600 # 1 hour
        keys_to_delete = [k for k, v in LAST_EDIT_TIMES.items() if v < cutoff]
        for k in keys_to_delete:
            del LAST_EDIT_TIMES[k]
    
    # Throttle check
    if msg_id in LAST_EDIT_TIMES:
        if (current_time - LAST_EDIT_TIMES[msg_id]) < EDIT_THROTTLE_SECONDS:
            return  # Skip update to protect API quotas

    try:
        await message.edit_text(text, parse_mode='Markdown')
        LAST_EDIT_TIMES[msg_id] = time.time()
    except RetryAfter as e:
        logging.warning(f"🤫 Status update throttled by Telegram (waiting {e.retry_after}s), skipping.")
        LAST_EDIT_TIMES[msg_id] = current_time + e.retry_after
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
    
    force_mtproto_fallback = False
    
    for batch_idx, batch in enumerate(batches):
        batch_start = batch_idx * batch_size + 1
        batch_end = min((batch_idx + 1) * batch_size, total_files)
        
        # Announce batch upload BEFORE the cooling delay to space out API calls
        await safe_edit_text(status_msg, f"🚀 *Uploading...*\n(Batch {batch_idx+1}/{len(batches)})")
        
        # Proactive cooling delay between batches to avoid rate limits
        if batch_idx > 0:
            await asyncio.sleep(5)

        # Check for Bot API limits (Per file >50MB OR Total Payload >45MB to be safe)
        large_files = [f for f in batch if os.path.exists(f) and os.path.getsize(f) > 50 * 1024 * 1024]
        total_batch_size = sum([os.path.getsize(f) for f in batch if os.path.exists(f)])
        
        # MTProto Fallback: Use it if forced OR if any limit is hit
        use_mtproto = force_mtproto_fallback or bool((large_files or total_batch_size > 45 * 1024 * 1024) and mtproto_client and mtproto_client.is_connected)
        
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

        # Recursive-style retry loop for Bot API
        attempts = 0
        max_attempts = 3
        while attempts < max_attempts:
            # Recreate media_group to ensure fresh, unread file handles per attempt
            media_group = []
            for file_path in batch:
                if not os.path.exists(file_path): continue
                
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ('.jpg', '.jpeg', '.png', '.webp'):
                    media_group.append(InputMediaPhoto(media=open(file_path, 'rb')))
                elif ext in ('.mp4', '.mov', '.avi', '.mkv', '.webm'):
                    media_group.append(InputMediaVideo(media=open(file_path, 'rb')))
            
            if not media_group: 
                break

            try:
                # Increased timeout values specifically for heavy video batch sizes
                await update.effective_message.reply_media_group(
                    media=media_group,
                    read_timeout=120,
                    write_timeout=120,
                    pool_timeout=120
                )
                uploaded_count += len(batch)
                break
            except RetryAfter as e:
                attempts += 1
                wait_time = e.retry_after + 1
                logging.warning(f"⚠️ Flood control! Waiting {wait_time}s (Attempt {attempts}/{max_attempts})...")
                
                await safe_edit_text(status_msg, f"⏳ *Waiting...*\n({wait_time}s to resume)")
                await asyncio.sleep(wait_time)
            except (NetworkError, TimedOut) as e:
                attempts += 1
                logging.warning(f"⚠️ Network timeout ({e}). Retrying (Attempt {attempts}/{max_attempts})...")
                await asyncio.sleep(5)
            except Exception as e:
                error_str = str(e).lower()
                if "readerror" in error_str or "timeout" in error_str or "httpx" in error_str:
                    attempts += 1
                    logging.warning(f"⚠️ Network stream disconnected ({e}). Retrying (Attempt {attempts}/{max_attempts})...")
                    await asyncio.sleep(5)
                else:
                    logging.error(f"❌ Batch upload failed: {e}")
                    failed_count += len(batch)
                    break
            finally:
                # Close file handles safely
                for media in media_group:
                    if hasattr(media.media, 'close'): 
                        try:
                            media.media.close()
                        except:
                            pass
        else:
            # Reached max attempts
            failed_count += len(batch)
            
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
