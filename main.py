import os
import re
import tempfile
import uuid
from typing import Dict, List
import openpyxl
from telegram import Update, InputFile
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Global dictionaries for pending operations
pending_sources: Dict[int, Dict] = {}

class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        
        # Add handlers
        self.application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
    
    async def start(self):
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
    
    async def stop(self):
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.document:
            return
        
        message = update.message
        chat_id = message.chat_id
        doc = message.document
        
        # Check file type
        if not (doc.file_name.lower().endswith('.txt') or doc.file_name.lower().endswith('.xlsx')):
            await message.reply_text("❌ Please send TXT or Excel (.xlsx) file.")
            return
        
        # Check file size (max 10MB)
        if doc.file_size > 10 * 1024 * 1024:
            await message.reply_text("❌ File too large. Max size is 10MB.")
            return
        
        try:
            # Download the file
            file = await doc.get_file()
            temp_dir = os.path.join(tempfile.gettempdir(), "TelegramBotTemp")
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{doc.file_name}")
            
            await file.download_to_drive(temp_path)
            
            # Store pending file
            pending_sources[chat_id] = {
                "file_path": temp_path,
                "original_file_name": doc.file_name
            }
            
            lines_count = 0
            file_path = pending_sources[chat_id]["file_path"]

            try:
                if file_path.lower().endswith('.xlsx'):
                    lines = await self.process_excel_file(file_path, "")
                    lines_count = len(lines)
                elif file_path.lower().endswith('.txt'):
                    lines = await self.process_txt_file(file_path, "")
                    lines_count = len(lines)
                
                await message.reply_text(f"📥 Đã nhận file có {lines_count} gmail.\nVui lòng điền Source:")
                
            except Exception as e:
                await message.reply_text(f"⚠️ Lỗi khi đếm số lượng gmail: {str(e)}")
            
        except Exception as e:
            await message.reply_text(f"⚠️ Error: {str(e)}")
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        
        message = update.message
        chat_id = message.chat_id
        text = message.text.strip()
        
        if chat_id in pending_sources:
            pending_file = pending_sources.pop(chat_id)
            source = text.strip()
            
            try:
                await message.reply_text("⏳ Đang xử lý...")
                
                # Process the file based on type
                if pending_file["file_path"].lower().endswith('.xlsx'):
                    processed_lines = await self.process_excel_file(pending_file["file_path"], source)
                elif (pending_file["file_path"].lower().endswith('.txt')):
                    processed_lines = await self.process_txt_file(pending_file["file_path"], source)
                
                if not processed_lines:
                    await message.reply_text("❌ Không thấy tài khoản Gmail nào trong file.")
                    return
                
                try:
                    # Create output TXT file
                    processed_path = os.path.join(tempfile.gettempdir(), f"processed_{uuid.uuid4()}.txt")
                    with open(processed_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(processed_lines))
                    
                    # Create response filename
                    clean_source = re.sub(r'[^\w\-_]', '_', source)
                    original_name = os.path.splitext(pending_file['original_file_name'])[0]
                    response_filename = f"{clean_source}_{original_name}.txt"
                    
                    # Send the processed file
                    with open(processed_path, 'rb') as file_to_send:
                        await message.reply_document(
                            document=InputFile(file_to_send, filename=response_filename),
                            caption=f"✅ Đã xử lý {len(processed_lines)} Gmail\nSource: {source}"
                        )
                
                except Exception as e:
                    await message.reply_text(f"⚠️ Error while creating/sending file: {str(e)}")
                
                finally:
                    # Clean up files
                    for path in [pending_file["file_path"], processed_path]:
                        if path and os.path.exists(path):
                            try:
                                os.remove(path)
                            except:
                                pass
            
            except Exception as e:
                await message.reply_text(f"⚠️ Processing error: {str(e)}")
                if 'pending_file' in locals() and os.path.exists(pending_file["file_path"]):
                    try:
                        os.remove(pending_file["file_path"])
                    except:
                        pass

    async def process_txt_file(self, path: str, source: str) -> List[str]:
        formatted = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                    
                parts = re.sub(r'\s+', ' ', line).strip().split(' ')
                parts = [p for p in parts if p]
                
                if parts and "@gmail.com" in parts[0].lower():
                    if len(parts) == 1:
                        result = f"{parts[0]}|aass1122|SOURCE_{source}_SOURCE"
                    elif len(parts) == 2:
                        result = f"{parts[0]}|{parts[1]}|SOURCE_{source}_SOURCE"
                    else:
                        result = f"{parts[0]}|{parts[1]}|{parts[2]}|SOURCE_{source}_SOURCE"
                        
                    formatted.append(result)
        return formatted

    async def process_excel_file(self, path: str, source: str) -> List[str]:
        lines = []
        try:
            workbook = openpyxl.load_workbook(path)
            worksheet = workbook.active
            
            for row in worksheet.iter_rows(min_row=2, values_only=True):
                try:
                    email = ""
                    password = ""
                    recovery = ""
                    emails = []
                    non_emails = []
                    
                    for cell in row[:5]:  # Check first 5 columns
                        if cell is None:
                            continue
                            
                        text = str(cell).strip()
                        if not text:
                            continue
                            
                        if '@' in text and '.' in text:
                            emails.append(text)
                        else:
                            non_emails.append(text)
                            
                    if emails:
                        email = emails[0]
                        if len(emails) > 1:
                            recovery = emails[1]
                            
                    password = non_emails[0] if non_emails else "aass1122"
                    
                    if email:
                        line = f"{email}|{password}"
                        if recovery:
                            line += f"|{recovery}"
                        line += f"|SOURCE_{source}_SOURCE"
                        lines.append(line)
                        
                except Exception as e:
                    print(f"Error processing row: {e}")
                    
        except Exception as e:
            print(f"Error processing Excel file: {e}")
            raise
            
        return lines


async def main():
    # Get token from environment variable
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable")
        
    bot = TelegramBot(token)
    await bot.start()
    
    # Keep the bot running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    import asyncio
    import dotenv
    dotenv.load_dotenv()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")