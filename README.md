# Video Editor Application

Uma aplicação web para edição de vídeos usando FFmpeg e MoviePy, com interface construída em TailwindCSS.

## Funcionalidades

- Processamento de vídeos usando FFmpeg
- Interface responsiva com TailwindCSS
- Suporte para redimensionamento de vídeos
- Recorte de vídeos com tempos específicos
- Aplicação de filtros

## Requisitos

- Python 3.8+
- FFmpeg
- MoviePy
- Flask
- TailwindCSS

## Instalação

1. Clone o repositório:
```bash
git clone https://github.com/seu-usuario/video-editor.git
cd video-editor
```

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. Configure o ambiente:
```bash
cp .env.example .env
```

4. Execute a aplicação:
```bash
python app/app.py
```

## Estrutura do Projeto
```
video-editor/
├── app/
│   ├── templates/
│   ├── static/
│   └── app.py
├── .gitignore
├── README.md
└── requirements.txt
```