import email
import imaplib
import smtplib
import os
import sqlite3
import time
import zipfile
import io
import re
import tarfile
import requests
from datetime import datetime, timedelta
from email.utils import getaddresses
from email.message import Message
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.header import decode_header, make_header
from dotenv import load_dotenv  # <--- NOVO: Biblioteca para ler o .env
import xml.etree.ElementTree as ET

# Tenta importar a biblioteca para .rar, se não existir, o suporte será desativado
try:
    import rarfile
    RAR_SUPPORT_ENABLED = True
except ImportError:
    RAR_SUPPORT_ENABLED = False
    print("\n\033[93m--> [AVISO] Biblioteca 'rarfile' não encontrada. O suporte a arquivos .rar está desativado.\033[0m")
    print("\033[93m--> Para ativar, execute: pip install rarfile e coloque o UnRAR.exe na pasta.\033[0m")


class EmailBot:
    """
    Automatiza o recebimento de e-mails, extrai arquivos XML de anexos, de arquivos
    compactados e de links (diretos e Google Drive), e envia uma resposta de confirmação.
    """
    # (O restante da classe EmailBot permanece exatamente o mesmo, sem alterações)
    # ... cole toda a sua classe EmailBot aqui, desde o __init__ até o run_cycle ...
    def __init__(self, config: dict):
        self.config = config
        self.filters = config.get("FILTERS", {})
        self.db_path = self.config.get("ARQUIVO_LOG", "historico_downloads.db")
        self.base_download_path = self.config["PASTA_DOWNLOAD"]

        # Verifica se o caminho de download foi carregado do .env
        if not self.base_download_path:
            raise ValueError("ERRO: O caminho de download (DOWNLOAD_PATH) não foi encontrado no arquivo .env.")

        os.makedirs(self.base_download_path, exist_ok=True)
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_database()

    def _get_db_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_database(self):
        with self._get_db_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logs_xml (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_key TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    data_download TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _build_search_criteria(self) -> str:
        criteria = ["UNANSWERED"]
        if self.filters.get("UNSEEN"):
            criteria.append("UNSEEN")
        days_ago = self.filters.get("SINCE_DAYS_AGO")
        if isinstance(days_ago, int):
            since_date = (datetime.now() - timedelta(days=days_ago)).strftime("%d-%b-%Y")
            criteria.append(f'(SINCE "{since_date}")')
        return " ".join(criteria)

    def _is_file_in_log(self, file_identifier: str) -> bool:
        with self._get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM logs_xml WHERE log_key = ? LIMIT 1",
                (file_identifier,)
            )
            return cursor.fetchone() is not None

    def _log_downloaded_file(self, file_identifier: str, filename: str):
        data_download = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO logs_xml (log_key, filename, data_download)
                VALUES (?, ?, ?)
                """,
                (file_identifier, filename, data_download)
            )
            conn.commit()

    def _sanitize_foldername(self, name: str) -> str:
        name = re.sub(r'[\x00-\x1f\r\n]', '', name).strip()
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        name = name.rstrip('. ')
        return name[:150] if len(name) > 150 else (name or "Pasta Sem Titulo Valido")

    def _send_reply(self, original_msg: Message):
        original_message_id = original_msg.get('Message-ID')
        if not original_message_id:
            print("--> [AVISO] Message-ID não encontrado. Não é possível responder na thread.")
            return

        recipients = set()
        addrs = getaddresses(original_msg.get_all('Reply-To', [])) or getaddresses(original_msg.get_all('From', []))
        for _, email_addr in addrs:
            if email_addr: recipients.add(email_addr)

        for header in ['To', 'Cc']:
            for _, email_addr in getaddresses(original_msg.get_all(header, [])):
                if email_addr: recipients.add(email_addr)

        recipients.discard(self.config['EMAIL_USUARIO'].lower())
        no_reply_keywords = {'no-reply', 'noreply', 'naoresponder'}
        final_recipients = {addr for addr in recipients if not any(keyword in addr.lower() for keyword in no_reply_keywords)}

        if not final_recipients:
            admin_email = self.config.get("ADMIN_EMAIL")
            if admin_email:
                print(f"--> [AVISO] Nenhum destinatário válido. Notificando admin: {admin_email}")
                final_recipients = {admin_email}
            else:
                print("--> [ERRO] Nenhum destinatário válido e nenhum ADMIN_EMAIL configurado.")
                return

        final_recipients_list = list(final_recipients)
        print(f"--> [AÇÃO] Preparando resposta para: {', '.join(final_recipients_list)}")
        try:
            reply_msg = MIMEMultipart('related')
            reply_msg['From'] = f"BergBot Fiscal <{self.config['EMAIL_USUARIO']}>"
            reply_msg['To'] = ", ".join(final_recipients_list)
            original_subject = str(make_header(decode_header(original_msg['Subject'])))
            reply_msg['Subject'] = f"Re: {original_subject}"
            reply_msg['In-Reply-To'] = original_message_id
            reply_msg['References'] = f"{original_msg.get('References', '')} {original_message_id}".strip()
            html_body = """<html><body><p>Olá,</p><p>O BergBot confirma o recebimento e o processamento dos arquivos XML enviados.</p><br><img src="cid:bergbot_logo"></body></html>"""
            reply_msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            try:
                with open('BergBot.jpeg', 'rb') as img_file:
                    img = MIMEImage(img_file.read())
                    img.add_header('Content-ID', '<bergbot_logo>')
                    reply_msg.attach(img)
            except FileNotFoundError:
                print("\n\033[91m--> [ERRO DE IMAGEM] 'BergBot.jpeg' não encontrado. E-mail sem imagem.\033[0m")

            with smtplib.SMTP(self.config["SMTP_SERVIDOR"], self.config["SMTP_PORTA"]) as server:
                server.starttls()
                server.login(self.config["EMAIL_USUARIO"], self.config["EMAIL_SENHA"])
                server.sendmail(self.config["EMAIL_USUARIO"], final_recipients_list, reply_msg.as_string())
            print("--> [SUCESSO] Resposta enviada.")
        except Exception as e:
            print(f"--> [ERRO] Falha ao enviar resposta: {e}")

    def _extract_xml_from_archive_recursively(self, archive_data: io.BytesIO, parent_log_key: str, archive_type: str) -> list[dict]:
        xmls_found = []
        archive_ref = None
        try:
            if archive_type == 'zip':
                archive_ref = zipfile.ZipFile(archive_data, 'r')
                file_list = archive_ref.infolist()
            elif archive_type == 'rar' and RAR_SUPPORT_ENABLED:
                archive_ref = rarfile.RarFile(archive_data, 'r')
                file_list = archive_ref.infolist()
            elif archive_type == 'tar':
                archive_data.seek(0)
                archive_ref = tarfile.open(fileobj=archive_data)
                file_list = archive_ref.getmembers()
            else:
                return []

            print(f"--> [ANÁLISE DE ARQUIVO COMPACTADO] Vasculhando '{parent_log_key}'...")
            for member_info in file_list:
                file_in_archive = member_info.filename if archive_type in ['zip', 'rar'] else member_info.name
                if (hasattr(member_info, 'is_dir') and member_info.is_dir()) or \
                   (hasattr(member_info, 'isdir') and member_info.isdir()):
                    continue

                def get_content(member):
                    if archive_type in ['zip', 'rar']: return archive_ref.read(member)
                    elif archive_type == 'tar':
                        extracted_file = archive_ref.extractfile(member)
                        return extracted_file.read() if extracted_file else None
                    return None

                content = get_content(member_info)
                if not content: continue
                
                filename_lower = file_in_archive.lower()
                if filename_lower.endswith('.xml'):
                    print(f"--> [XML ENCONTRADO] Coletando '{file_in_archive}' de '{parent_log_key}'")
                    xmls_found.append({"filename": os.path.basename(file_in_archive), "content": content, "log_key": f"{parent_log_key}/{file_in_archive}"})
                elif filename_lower.endswith(('.zip', '.rar', '.tar', '.gz', '.bz2', '.tgz')):
                    nested_archive_type = 'tar' if not filename_lower.endswith(('.zip', '.rar')) else filename_lower.split('.')[-1]
                    print(f"--> [ARQUIVO ANINHADO] Encontrado '{file_in_archive}'. Analisando...")
                    nested_data = io.BytesIO(content)
                    nested_xmls = self._extract_xml_from_archive_recursively(nested_data, f"{parent_log_key}/{file_in_archive}", nested_archive_type)
                    xmls_found.extend(nested_xmls)
        except Exception as e:
            print(f"--> [ERRO AO EXTRAIR] Falha ao processar '{parent_log_key}': {e}")
        finally:
            if archive_ref: archive_ref.close()
        return xmls_found

    def _identify_file_type_from_content(self, content: bytes) -> str | None:
        if not content:
            return None
        
        if content.startswith(b'\x50\x4b\x03\x04'): return 'zip'
        if RAR_SUPPORT_ENABLED and content.startswith(b'Rar!'): return 'rar'
        try:
            if tarfile.is_tarfile(io.BytesIO(content)): return 'tar'
        except Exception: pass
        try:
            if content[:50].decode('utf-8', errors='ignore').strip().lower().startswith('<?xml'): return 'xml'
        except Exception: pass
        return None

    def _is_valid_xml(self, content: bytes) -> bool:
        if not content:
            return False
        try:
            # xml.etree accepts bytes or str; this will validate well-formedness
            ET.fromstring(content)
            return True
        except Exception:
            return False

    def _process_links_in_email_body(self, email_message: Message) -> list[dict]:
        all_xmls_from_links = []
        url_pattern = re.compile(r'https?://[^\s<>"]+')
        processed_urls = set()

        for part in email_message.walk():
            if part.get_content_type() in ['text/plain', 'text/html']:
                try:
                    body_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    continue

                for url in url_pattern.findall(body_text):
                    url = url.strip('.,')
                    if url in processed_urls:
                        continue
                    processed_urls.add(url)

                    if 'drive.google.com/file/d/' not in url:
                        continue

                    print(f"--> [LINK GOOGLE DRIVE VÁLIDO] Encontrado: {url}")
                    file_id_match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
                    if not file_id_match:
                        print("--> [AVISO] Link do Drive não contém um ID de arquivo reconhecível. Ignorando.")
                        continue
                    
                    file_id = file_id_match.group(1)
                    download_url = f'https://drive.google.com/uc?export=download&id={file_id}'
                    print(f"--> [CONVERSÃO] Tentando download direto via: {download_url}")

                    try:
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        response = requests.get(download_url, timeout=45, headers=headers, allow_redirects=True)
                        response.raise_for_status()
                        content_bytes = response.content

                        filename_from_url = ""
                        if 'content-disposition' in response.headers:
                            cd = response.headers['content-disposition']
                            fname_match = re.search(r'filename="?([^"]+)"?', cd)
                            if fname_match:
                                filename_from_url = fname_match.group(1)
                                print(f"--> [INFO] Nome do arquivo obtido do cabeçalho: '{filename_from_url}'")
                        
                        file_type = ""
                        if filename_from_url:
                            fn_lower = filename_from_url.lower()
                            if fn_lower.endswith('.xml'): file_type = 'xml'
                            elif fn_lower.endswith('.zip'): file_type = 'zip'
                            elif fn_lower.endswith('.rar') and RAR_SUPPORT_ENABLED: file_type = 'rar'
                            elif fn_lower.endswith(('.tar', '.gz', '.bz2', '.tgz')): file_type = 'tar'

                        if not file_type:
                            print("--> [INFO] Nome do arquivo não ajudou. Analisando conteúdo (magic numbers)...")
                            file_type = self._identify_file_type_from_content(content_bytes)
                            if file_type:
                                print(f"--> [SUCESSO] Conteúdo identificado como: '{file_type}'")

                        if not filename_from_url and file_type:
                            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                            filename_from_url = f"download_do_drive_{timestamp}.{file_type}"
                            print(f"--> [AVISO] Nome de arquivo ausente. Usando nome genérico: '{filename_from_url}'")

                        if not file_type:
                            print(f"--> [AVISO] Não foi possível determinar o tipo do arquivo para o link '{url}'. Ignorando.")
                            continue
                        
                        print(f"--> [DOWNLOAD SUCESSO] Baixado '{filename_from_url}' do link.")

                        if file_type == 'xml':
                            all_xmls_from_links.append({"filename": filename_from_url, "content": content_bytes, "log_key": url})
                        elif file_type in ['zip', 'rar', 'tar']:
                            data_in_memory = io.BytesIO(content_bytes)
                            xmls_in_archive = self._extract_xml_from_archive_recursively(
                                data_in_memory, parent_log_key=url, archive_type=file_type)
                            all_xmls_from_links.extend(xmls_in_archive)

                    except requests.exceptions.RequestException as e:
                        print(f"--> [ERRO DE DOWNLOAD] Falha ao baixar o link '{url}': {e}")
                    except Exception as e:
                        print(f"--> [ERRO INESPERADO] Problema ao processar link '{url}': {e}")
        return all_xmls_from_links

    def _find_xml_attachments(self, email_message: Message) -> list[dict]:
        xml_attachments = []
        for part in email_message.walk():
            raw_filename = part.get_filename()
            if not raw_filename or part.get('Content-Disposition') is None:
                continue

            try:
                decoded_header = decode_header(raw_filename)
                filename = str(make_header(decoded_header))
            except Exception:
                filename = raw_filename
                print(f"--> [AVISO] Falha ao decodificar nome do anexo: '{raw_filename}'.")

            print(f"--> [ANEXO DETECTADO] Verificando: '{filename}'")
            filename_lower = filename.lower()
            is_xml = filename_lower.endswith('.xml')
            is_zip = filename_lower.endswith('.zip')
            is_rar = RAR_SUPPORT_ENABLED and filename_lower.endswith('.rar')
            is_tar = filename_lower.endswith(('.tar', '.gz', '.bz2', '.tgz'))
            
            if is_xml:
                content = part.get_payload(decode=True)
                if content and self._is_valid_xml(content):
                    print(f"--> [XML DIRETO] Anexo qualificado: '{filename}'")
                    xml_attachments.append({"filename": filename, "content": content, "log_key": filename})
                else:
                    print(f"--> [IGNORADO] Anexo '{filename}' não é um XML válido ou está vazio.")
            elif is_zip or is_rar or is_tar:
                print(f"--> [ARQUIVO COMPACTADO] Anexo qualificado: '{filename}'")
                archive_type = 'zip' if is_zip else 'rar' if is_rar else 'tar'
                archive_data = io.BytesIO(part.get_payload(decode=True))
                xmls_in_archive = self._extract_xml_from_archive_recursively(archive_data, parent_log_key=filename, archive_type=archive_type)
                # Filtra apenas XMLs bem-formados extraídos do arquivo compactado
                valid_xmls = []
                for x in xmls_in_archive:
                    if x.get("content") and self._is_valid_xml(x.get("content")):
                        valid_xmls.append(x)
                    else:
                        print(f"--> [IGNORADO] Arquivo extraído '{x.get('filename')}' não é um XML válido.")
                xml_attachments.extend(valid_xmls)
            else:
                print(f"--> [IGNORADO] Anexo '{filename}' não é um formato suportado.")
        return xml_attachments

    def _save_xml_and_log(self, xml_data: list[dict], folder_path: str) -> bool:
        any_new_downloads = False
        os.makedirs(folder_path, exist_ok=True)
        for xml_item in xml_data:
            safe_filename = os.path.basename(xml_item["filename"])
            final_xml_path = os.path.join(folder_path, safe_filename)
            log_key = xml_item["log_key"]

            if self._is_file_in_log(log_key):
                print(f"--> [DUPLICADO NO LOG] Chave '{log_key}' já processada.")
                continue
            if os.path.exists(final_xml_path):
                print(f"--> [DUPLICADO NO DISCO] Arquivo '{safe_filename}' já existe. Adicionando ao log.")
                self._log_downloaded_file(log_key, safe_filename)
                continue

            # Verifica se o conteúdo é um XML bem-formado antes de salvar
            content = xml_item.get("content")
            if not content or not self._is_valid_xml(content):
                print(f"--> [IGNORADO] Conteúdo de '{safe_filename}' não é um XML válido. Não será salvo.")
                continue

            try:
                with open(final_xml_path, 'wb') as f:
                    f.write(content)
                self._log_downloaded_file(log_key, safe_filename)
                any_new_downloads = True
                print(f"--> [SALVO] '{safe_filename}' salvo em: {folder_path}")
            except OSError as e:
                print(f"--> [ERRO AO SALVAR] Não foi possível salvar '{safe_filename}': {e}")
        return any_new_downloads

    def _process_email(self, mail: imaplib.IMAP4_SSL, email_id: bytes):
        status, msg_data = mail.fetch(email_id, '(RFC822)')
        if status != 'OK':
            print(f"--> [ERRO] Falha ao buscar e-mail ID {email_id.decode()}.")
            return
        
        email_message = email.message_from_bytes(msg_data[0][1])
        email_subject = str(make_header(decode_header(email_message["subject"])))
        # Segurança: ignorar e-mails internos da própria empresa
        from_header = (email_message.get('From') or '')
        from_header_lower = from_header.lower()
        print(f"\n--- Analisando e-mail de: {from_header} | Assunto: '{email_subject}' ---")

        # Caso o e-mail venha do domínio interno, marcar como lido e pular processamento
        internal_domain = '@rpscontabil.com.br'
        if internal_domain in from_header_lower:
            print(f"--> [IGNORADO - INTERNO] E-mail vindo do domínio interno '{internal_domain}' detectado em '{from_header}'. Ignorando e marcando como lido.")
            try:
                mail.store(email_id, '+FLAGS', '\\Seen')
            except Exception as e:
                print(f"--> [AVISO] Falha ao marcar e-mail como lido: {e}")
            return

        xml_from_attachments = self._find_xml_attachments(email_message)
        xml_from_links = self._process_links_in_email_body(email_message)
        xml_to_process = xml_from_attachments + xml_from_links

        if not xml_to_process:
            print("--> [INFO] Nenhum arquivo XML processável encontrado. Marcando como lido.")
            mail.store(email_id, '+FLAGS', '\\Seen')
            return
        
        download_folder = self.base_download_path
        found_new_files = self._save_xml_and_log(xml_to_process, download_folder)
        
        if found_new_files:
            self._send_reply(email_message)
            mail.store(email_id, '+FLAGS', '\\Seen \\Answered')
            print(f"--> [INFO] E-mail ID {email_id.decode()} processado e marcado como Lido e Respondido.")
        else:
            # Não responder se nenhum novo XML foi salvo; apenas marcar como lido
            print("--> [INFO] Nenhum XML novo foi salvo. Não será enviada resposta.")
            mail.store(email_id, '+FLAGS', '\\Seen')
            print(f"--> [INFO] E-mail ID {email_id.decode()} marcado apenas como Lido.")

    def run_cycle(self):
        print(f"\n--- [CICLO INICIADO] {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} ---")
        try:
            with imaplib.IMAP4_SSL(self.config["IMAP_SERVIDOR"]) as mail:
                mail.login(self.config["EMAIL_USUARIO"], self.config["EMAIL_SENHA"])
                mail.select('inbox')
                search_criteria = self._build_search_criteria()
                print(f"--> [BUSCA] Usando critério: {search_criteria}...")
                status, messages = mail.search(None, search_criteria)
                if status != 'OK' or not messages[0]:
                    print("--> [INFO] Nenhum e-mail novo (e não respondido) encontrado.")
                    return

                email_ids = messages[0].split()
                print(f"--> [INFO] {len(email_ids)} e-mail(s) para processar.")
                for email_id in reversed(email_ids):
                    self._process_email(mail, email_id)
        except imaplib.IMAP4.error as e:
            print(f"\n\033[93m--> [ERRO IMAP] Problema de conexão ou autenticação: {e}\033[0m")
        except Exception as e:
            print(f"\n\033[93m--> [ERRO NO CICLO] Problema inesperado: {e}\033[0m")


def send_whatsapp_notification(phone_numbers: list[str], message: str):
    if not phone_numbers:
        print("\n\033[93m--> [AVISO WHATSAPP] Lista de números vazia.\033[0m")
        return
    try:
        import pywhatkit
        print(f"\n\033[96m--> [AÇÃO WHATSAPP] Enviando para {len(phone_numbers)} número(s)...\033[0m")
        for number in phone_numbers:
            try:
                print(f"--> Enviando para {number}...")
                pywhatkit.sendwhatmsg_instantly(phone_no=number, message=message, wait_time=20, tab_close=True, close_time=5)
                print(f"\033[92m--> Sucesso! Mensagem para {number} enviada.\033[0m")
                time.sleep(10)
            except Exception as e:
                print(f"\n\033[91m--> [ERRO WHATSAPP] Falha ao enviar para {number}: {e}\033[0m")
        print("\033[92m--> [PROCESSO FINALIZADO] Todas as notificações processadas.\033[0m")
    except ImportError:
        print(f"\n\033[91m--> [ERRO CRÍTICO WHATSAPP] Lib 'pywhatkit' não instalada.\033[0m")
    except Exception as e:
        print(f"\n\033[91m--> [ERRO CRÍTICO WHATSAPP] {e}\033[0m")

def main():
    # <--- ALTERADO: Carrega as variáveis de ambiente do arquivo .env
    load_dotenv()

    # <--- NOVO: Pega a string de telefones do .env e transforma em uma lista
    phones_str = os.getenv("WHATSAPP_PHONES", "") # Pega a string, ou uma string vazia se não existir
    whatsapp_phones_list = [phone.strip() for phone in phones_str.split(',')] if phones_str else []

    # <--- ALTERADO: O dicionário agora lê as informações do .env
    CONFIG = {
        # Informações sensíveis carregadas do .env
        "EMAIL_USUARIO": os.getenv("EMAIL_USER"),
        "EMAIL_SENHA": os.getenv("EMAIL_PASSWORD"),
        "ADMIN_EMAIL": os.getenv("ADMIN_EMAIL"),
        "PASTA_DOWNLOAD": os.getenv("DOWNLOAD_PATH"),
        "WHATSAPP_RECIPIENT_PHONES": whatsapp_phones_list,

        # Configurações não-sensíveis que podem continuar no código
        "IMAP_SERVIDOR": "imap.gmail.com",
        "SMTP_SERVIDOR": "smtp.gmail.com",
        "SMTP_PORTA": 587,
        "ARQUIVO_LOG": "historico_downloads.db",
        "INTERVALO_SEGUNDOS": 60,
        "FILTERS": {"UNSEEN": False, "SINCE_DAYS_AGO": 3},
        "ENABLE_WHATSAPP_NOTIFICATION": True,
    }

    print("--- Iniciando Bot de Automação de E-mail ---")
    bot = EmailBot(config=CONFIG)
    try:
        while True:
            bot.run_cycle()
            print(f"--- [CICLO FINALIZADO] --- Aguardando {CONFIG['INTERVALO_SEGUNDOS']} segundos.")
            time.sleep(CONFIG['INTERVALO_SEGUNDOS'])
    except KeyboardInterrupt:
        print("\n\033[96m--- [AVISO] Bot interrompido manualmente. Encerrando... ---\033[0m")
        if CONFIG.get("ENABLE_WHATSAPP_NOTIFICATION"):
            message = "🚨 *Alerta BergBot* 🚨\n\nO bot de e-mails foi *interrompido manualmente*."
            send_whatsapp_notification(CONFIG.get("WHATSAPP_RECIPIENT_PHONES", []), message)
    except Exception as e:
        error_details = f"🚨 *Alerta BergBot - ERRO FATAL* 🚨\n\nO bot encontrou um erro crítico e foi encerrado.\n\n*Motivo:* {e}"
        print("\n\033[91m" + "="*70)
        print("      🚨 FATAL: O BOT ENCONTROU UM ERRO CRÍTICO E SERÁ ENCERRADO. 🚨")
        print(f"      MOTIVO: {e}")
        print("="*70 + "\033[0m")
        if CONFIG.get("ENABLE_WHATSAPP_NOTIFICATION"):
            send_whatsapp_notification(CONFIG.get("WHATSAPP_RECIPIENT_PHONES", []), error_details)
    finally:
        print("--- [SESSÃO FINALIZADA] ---")

if __name__ == "__main__":
    main()