# app.py
from flask import Flask, jsonify
from flask_cors import CORS
from flasgger import Swagger
from dotenv import load_dotenv
import os

from src.aluno import alunos_bp
from src.professora import professores_bp
from src.atividades import atividades_bp
from src.relatorios import relatorios_bp

load_dotenv()

app = Flask(__name__)

app.config['SWAGGER'] = {
    'openapi': '3.0.0'
}

swagger = Swagger(app, template_file='openapi.yaml')
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")

# Suporte total a CORS para Vercel e chamadas de origens externas
CORS(app, resources={r"/*": {"origins": "*"}})

# Registro dos módulos organizados por prefixo
app.register_blueprint(professores_bp, url_prefix='/professores')
app.register_blueprint(alunos_bp, url_prefix='/alunos')
app.register_blueprint(atividades_bp, url_prefix='/atividades')
app.register_blueprint(relatorios_bp, url_prefix='/relatorios')

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "online",
        "projeto": "Roar API",
        "versao": "1.0.0"
    }), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)
