import os
from flask import Flask, jsonify
from flask_cors import CORS
from flasgger import Swagger
from  dotenv import load_dotenv
from src.aluno import alunos_bp
from src.professora import professores_bp
from src.atividades import atividades_bp

load_dotenv()

app = Flask(__name__)

#VERSÃO do OPEN API
app.config['SWAGGER'] = {
    'openapi':'3.0.0'
}

swagger = Swagger(app, template_file='openapi.yaml')


app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")

CORS(app, origins="*")

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