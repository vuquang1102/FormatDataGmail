import os
import re
import tempfile
import uuid
import concurrent.futures
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

import openpyxl
from telegram import Update, InputFile, Document, Message
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Global dictionaries for pending operations
pending_sources: Dict[int, Dict] = {}
pending_text_lines: Dict[int, List[str]] = {}

class TelegramBot:
    def __init__(self, token: str = "7667500548:AAHHC_-qbELiDWoFjHKYnNBT2UwWtt26DxY"):
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
        file_name = doc.file_name.lower()
        
        if not (file_name.endswith('.txt') or file_name.endswith('.xlsx')):
            await message.reply_text("❌ Vui lòng gửi file TXT hoặc Excel (.xlsx).")
            return
        
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
        
        await message.reply_text("📥 Đã nhận file. Vui lòng nhập source bạn muốn gán cho mỗi dòng:")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        
        message = update.message
        chat_id = message.chat_id
        text = message.text.strip()
        
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Check if user is responding to a pending file
        if chat_id in pending_sources:
            pending_file = pending_sources.pop(chat_id)
            source = text
            
            if pending_file["file_path"].lower().endswith('.xlsx'):
                processed_path = await self.process_excel_file_with_source(pending_file["file_path"], source)
            else:
                processed_path = await self.process_txt_file_with_source(pending_file["file_path"], source)
            
            # Read the processed file
            with open(processed_path, 'r', encoding='utf-8') as f:
                lines_processed = f.readlines()
                total = len(lines_processed)
                
            clean_source = source.replace(" ", "_").replace("|", "_").replace(":", "_")
            file_name = f"SOURCE_{clean_source}_{total}.txt"
            
            await message.reply_document(
                document=InputFile(processed_path, filename=file_name),
                caption=f"✅ File đã xử lý với tổng {total} tài khoản Gmail và Source: {source}"
            )
            
            # Clean up
            os.remove(pending_file["file_path"])
            os.remove(processed_path)
            
        # Check if user is responding to pending text lines
        elif chat_id in pending_text_lines:
            raw_lines = pending_text_lines.pop(chat_id)
            source = text
            formatted = self.format_gmail_lines(raw_lines, source)
            output_path = os.path.join(tempfile.gettempdir(), f"gmail_list_{uuid.uuid4()}.txt")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(formatted))
                
            await message.reply_document(
                document=InputFile(output_path, filename="processed.txt"),
                caption="✅ Text đã xử lý"
            )
            
            os.remove(output_path)
            
        # Check if user sent multiple Gmail lines
        elif len(lines) >= 2 and all(self.is_gmail_line(line) for line in lines):
            pending_text_lines[chat_id] = lines
            await message.reply_text("📋 Đã nhận danh sách Gmail. Vui lòng nhập source để xử lý:")
            
        else:
            await message.reply_text("❗ Vui lòng gửi file .txt hoặc danh sách Gmail hợp lệ.")

    async def process_txt_file_with_source(self, path: str, source: str) -> str:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        formatted = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            parts = re.sub(r'\s+', ' ', line).strip().split(' ')
            parts = [p for p in parts if p]
            
            if parts and "@gmail.com" in parts[0].lower():
                if len(parts) == 1:
                    # Only email
                    result = f"{parts[0]}|aass1122|SOURCE_{source}_SOURCE"
                elif len(parts) == 2:
                    # Email + password
                    result = f"{parts[0]}|{parts[1]}|SOURCE_{source}_SOURCE"
                else:
                    # Email + password + recovery or more
                    result = f"{parts[0]}|{parts[1]}|{parts[2]}|SOURCE_{source}_SOURCE"
                    
                formatted.append(result)
                
        out_dir = os.path.dirname(path)
        out_filename = "processed_" + os.path.basename(path)
        out_path = os.path.join(out_dir, out_filename)
        
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(formatted))
            
        return out_path

    async def process_excel_file_with_source(self, path: str, source: str) -> str:
        out_path = os.path.join(tempfile.gettempdir(), f"processed_{uuid.uuid4()}.txt")
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
            
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
            
        return out_path

    def is_gmail_line(self, line: str) -> bool:
        if not line.strip():
            return False
            
        parts = re.split(r'[\t ]+', line.strip())
        parts = [p for p in parts if p]
        
        return len(parts) >= 2 and "@gmail.com" in parts[0].lower()

    def format_gmail_lines(self, lines: List[str], source: str) -> List[str]:
        formatted = []
        for line in lines:
            parts = re.split(r'[\t ]+', line.strip())
            parts = [p for p in parts if p]
            
            if len(parts) >= 2:
                result = f"{parts[0]}|{parts[1]}"
                
                if len(parts) == 2:
                    # No recovery
                    result += f"|SOURCE_{source}_SOURCE"
                else:
                    # With recovery
                    result += f"|{parts[2]}|SOURCE_{source}_SOURCE"
                    
                formatted.append(result)
            elif len(parts) == 1:
                result = f"{parts[0]}|aass1122|SOURCE_{source}_SOURCE"
                formatted.append(result)
                
        return formatted


async def main():
    # Get token from environment variable or configuration
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Telegram bot token is missing in configuration")
        
    bot = TelegramBot(token)
    await bot.start()
    
    # Keep the bot running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())