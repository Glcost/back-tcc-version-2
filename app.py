import os
from flask import Flask, jsonify
from flask_cors import CORS
from src.aluno import alunos_bp
from src.professora import professores_bp
from src.atividades import atividades_bp

app = Flask(__name__)

# Configuração estrita de CORS para o seu Front-end React
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Registro dos módulos da API Roar
app.register_blueprint(alunos_bp)
app.register_blueprint(professores_bp)
app.register_blueprint(atividades_bp)

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "online",
        "projeto": "Roar API",
        "versao": "1.0.0"
    }), 200

if __name__ == '__main__':
    # Roda localmente na porta 5000
    app.run(debug=True, port=5000)