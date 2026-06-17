# 🤖 BergBot - Automação Fiscal de E-mails

![Status](https://img.shields.io/badge/status-ativo-success)
![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/licen%C3%A7a-MIT-informational)

O BergBot automatiza o recebimento, o processamento e o armazenamento de XMLs enviados por e-mail. Agora o projeto conta com um dashboard separado em Streamlit e histórico centralizado em SQLite.

---

## ✨ Funcionalidades Principais

- 📥 Monitoramento contínuo de e-mails via IMAP.
- 📂 Extração de XMLs em anexos, arquivos compactados e links do Google Drive.
- ↪️ Resposta automática ao processar novos arquivos.
- 🗃️ Histórico de downloads salvo em SQLite no arquivo historico_downloads.db.
- 📊 Dashboard em Streamlit com filtros por data e busca por nome de arquivo.
- 🗂️ Organização centralizada dos XMLs em uma pasta de destino.
- 📲 Notificações via WhatsApp em caso de interrupção ou erro crítico.

---

## ⚙️ Estrutura do Projeto

- xmlemail.py: bot principal de e-mail.
- dashboard.py: tela analítica com Streamlit.
- historico_downloads.db: banco SQLite com o histórico de downloads.
- requirements.txt: dependências do projeto.

---

## 🛠️ Tecnologias Utilizadas

- Python 3
- sqlite3
- Streamlit
- Pandas
- Plotly Express
- requests
- rarfile
- pywhatkit
- python-dotenv

---

## 🚀 Instalação e Configuração

### 1. Pré-requisitos

- Python 3.9 ou superior.
- Conta de e-mail com IMAP ativado.
- Senha de aplicativo para autenticação no e-mail, se necessário.
- UnRAR, caso vá processar arquivos .rar.

### 2. Instalar as dependências

```bash
pip install -r requirements.txt
```

### 3. Configurar o arquivo .env

Exemplo:

```env
EMAIL_USER=seu-email@gmail.com
EMAIL_PASSWORD=sua-senha-de-app
DOWNLOAD_PATH=C:\Caminho\Para\Salvar\XMLs
ADMIN_EMAIL=email-admin@dominio.com
WHATSAPP_PHONES=+5573999998888,+5571988887777
```

### 4. Arquivos necessários

- Coloque o arquivo BergBot.jpeg na pasta principal.
- Se for usar .rar, mantenha o UnRAR.exe na mesma pasta do projeto.

---

## ▶️ Como Executar

### Terminal 1: bot principal

```bash
python xmlemail.py
```

### Terminal 2: dashboard

```bash
streamlit run dashboard.py
```

---

## 📊 Dashboard

O dashboard lê diretamente o banco historico_downloads.db e exibe:

- Total de XMLs baixados.
- XMLs filtrados.
- Gráfico de barras por dia.
- Tabela com ID, nome do arquivo e data/hora formatada no padrão brasileiro.
- Filtros de intervalo de datas e busca por texto no nome do arquivo.

---

## 🧠 Como Funciona

1. O bot conecta na caixa de e-mail.
2. Busca mensagens dentro dos critérios definidos.
3. Analisa anexos e links.
4. Extrai XMLs válidos.
5. Salva os arquivos no diretório configurado.
6. Registra log_key, filename e data_download no SQLite.
7. Responde ao e-mail quando houver novos XMLs processados.
8. Aguarda o próximo ciclo.

---

## 📝 Observações Importantes

- O arquivo log_downloads.txt não é mais utilizado.
- O histórico agora fica em historico_downloads.db.
- O dashboard e o bot devem ser executados em terminais separados.
- Se o banco ainda não existir, ele será criado automaticamente pelo bot.

---

## 📄 Licença

Este projeto está sob a licença MIT.
