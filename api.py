import os
from pathlib import Path

import click
from dotenv import load_dotenv
from flask import Flask, jsonify, request, url_for
import mysql.connector
from waitress import serve


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INIT_SQL_PATH = BASE_DIR / "db" / "init.sql"

CAMPO_OBRIGATORIOS = ("cidade", "logradouro")
CAMPOS_EDITAVEIS = (
	"logradouro",
	"tipo_logradouro",
	"bairro",
	"cidade",
	"cep",
	"tipo",
	"valor",
	"data_aquisicao",
)


def load_db():
	load_dotenv()
	kwargs = {
		"host": os.getenv("host"),
		"port": int(os.getenv("port", 3306)),
		"user": os.getenv("user"),
		"password": os.getenv("password"),
		"database": os.getenv("database"),
	}
	ssl_ca = os.getenv("ssl_ca")
	if ssl_ca:
		ca_path = Path(ssl_ca)
		if not ca_path.is_absolute():
			ca_path = (BASE_DIR / ca_path).resolve()
		kwargs["ssl_ca"] = str(ca_path)
	return mysql.connector.connect(**kwargs)


def create_app(db_factory=None):
	app = Flask(__name__)
	app.config["JSON_SORT_KEYS"] = False

	_factory = db_factory or load_db

	_registrar_rotas(app, lambda: _factory())
	_registrar_comandos(app, lambda: _factory())
	return app


def _registrar_rotas(app, get_db):
	@app.get("/imoveis")
	def listar_imoveis():
		tipo = request.args.get("tipo")
		cidade = request.args.get("cidade")
		conn = get_db()
		cursor = conn.cursor(dictionary=True)
		if tipo and cidade:
			cursor.execute(
				"SELECT * FROM imoveis WHERE LOWER(tipo)=%s AND LOWER(cidade)=%s ORDER BY id",
				(tipo.strip().lower(), cidade.strip().lower()),
			)
		elif tipo:
			cursor.execute(
				"SELECT * FROM imoveis WHERE LOWER(tipo)=%s ORDER BY id",
				(tipo.strip().lower(),),
			)
		elif cidade:
			cursor.execute(
				"SELECT * FROM imoveis WHERE LOWER(cidade)=%s ORDER BY id",
				(cidade.strip().lower(),),
			)
		else:
			cursor.execute("SELECT * FROM imoveis ORDER BY id")
		imoveis = cursor.fetchall()
		cursor.close()
		conn.close()
		return jsonify(imoveis)

	@app.get("/imoveis/tipo/<string:tipo>")
	def listar_imoveis_por_tipo(tipo):
		conn = get_db()
		cursor = conn.cursor(dictionary=True)
		cursor.execute(
			"SELECT * FROM imoveis WHERE LOWER(tipo)=%s ORDER BY id",
			(tipo.strip().lower(),),
		)
		imoveis = cursor.fetchall()
		cursor.close()
		conn.close()
		return jsonify(imoveis)

	@app.get("/imoveis/cidade/<path:cidade>")
	def listar_imoveis_por_cidade(cidade):
		conn = get_db()
		cursor = conn.cursor(dictionary=True)
		cursor.execute(
			"SELECT * FROM imoveis WHERE LOWER(cidade)=%s ORDER BY id",
			(cidade.strip().lower(),),
		)
		imoveis = cursor.fetchall()
		cursor.close()
		conn.close()
		return jsonify(imoveis)

	@app.get("/imoveis/<int:imovel_id>")
	def buscar_imovel(imovel_id):
		conn = get_db()
		cursor = conn.cursor(dictionary=True)
		cursor.execute("SELECT * FROM imoveis WHERE id=%s", (imovel_id,))
		imovel = cursor.fetchone()
		cursor.close()
		conn.close()
		if imovel is None:
			return _erro("Imovel nao encontrado", 404)
		return jsonify(imovel)

	@app.post("/imoveis")
	def criar_imovel():
		payload, erro = _validar_payload()
		if erro:
			return erro
		campos_ausentes = _campos_obrigatorios_ausentes(payload)
		if campos_ausentes:
			return _erro(
				f"Campos obrigatorios ausentes: {', '.join(campos_ausentes)}",
				400,
			)
		dados = _filtrar_campos(payload)
		colunas = ", ".join(dados.keys())
		placeholders = ", ".join(["%s"] * len(dados))
		valores = tuple(dados.values())
		conn = get_db()
		cursor = conn.cursor(dictionary=True)
		cursor.execute(
			f"INSERT INTO imoveis ({colunas}) VALUES ({placeholders})", valores
		)
		novo_id = cursor.lastrowid
		conn.commit()
		cursor.execute("SELECT * FROM imoveis WHERE id=%s", (novo_id,))
		imovel = cursor.fetchone()
		cursor.close()
		conn.close()
		resposta = jsonify(imovel)
		resposta.status_code = 201
		resposta.headers["Location"] = url_for("buscar_imovel", imovel_id=novo_id)
		return resposta

	@app.put("/imoveis/<int:imovel_id>")
	@app.patch("/imoveis/<int:imovel_id>")
	def atualizar_imovel(imovel_id):
		conn = get_db()
		cursor = conn.cursor(dictionary=True)
		cursor.execute("SELECT * FROM imoveis WHERE id=%s", (imovel_id,))
		imovel = cursor.fetchone()
		if imovel is None:
			cursor.close()
			conn.close()
			return _erro("Imovel nao encontrado", 404)
		payload, erro = _validar_payload()
		if erro:
			cursor.close()
			conn.close()
			return erro
		dados = _filtrar_campos(payload)
		novo_estado = {**imovel, **dados}
		campos_invalidos = sorted(
			campo for campo in CAMPO_OBRIGATORIOS if not novo_estado.get(campo)
		)
		if campos_invalidos:
			cursor.close()
			conn.close()
			return _erro(
				f"Campos obrigatorios ausentes: {', '.join(campos_invalidos)}",
				400,
			)
		if dados:
			sets = ", ".join(f"{k}=%s" for k in dados.keys())
			valores = tuple(dados.values()) + (imovel_id,)
			cursor.execute(f"UPDATE imoveis SET {sets} WHERE id=%s", valores)
			conn.commit()
		cursor.execute("SELECT * FROM imoveis WHERE id=%s", (imovel_id,))
		imovel_atualizado = cursor.fetchone()
		cursor.close()
		conn.close()
		return jsonify(imovel_atualizado)

	@app.delete("/imoveis/<int:imovel_id>")
	def remover_imovel(imovel_id):
		conn = get_db()
		cursor = conn.cursor(dictionary=True)
		cursor.execute("SELECT * FROM imoveis WHERE id=%s", (imovel_id,))
		imovel = cursor.fetchone()
		if imovel is None:
			cursor.close()
			conn.close()
			return _erro("Imovel nao encontrado", 404)
		cursor.execute("DELETE FROM imoveis WHERE id=%s", (imovel_id,))
		conn.commit()
		cursor.close()
		conn.close()
		return ("", 204)


def _registrar_comandos(app, get_db):
	@app.cli.command("init-db")
	@click.option("--reset", is_flag=True, help="Recria a tabela antes de carregar o script.")
	def init_db_command(reset):
		conn = get_db()
		cursor = conn.cursor()
		if reset:
			cursor.execute("DROP TABLE IF EXISTS imoveis")
		script = DEFAULT_INIT_SQL_PATH.read_text(encoding="utf-8")
		for stmt in script.split(";"):
			stmt = stmt.strip()
			if stmt and not stmt.startswith("--"):
				cursor.execute(stmt)
		conn.commit()
		cursor.close()
		conn.close()
		print("Banco inicializado com sucesso.")


def _validar_payload():
	payload = request.get_json(silent=True)
	if payload is None or not isinstance(payload, dict):
		return None, _erro("Corpo da requisicao deve ser um JSON valido", 400)
	return payload, None


def _filtrar_campos(payload):
	return {campo: payload[campo] for campo in CAMPOS_EDITAVEIS if campo in payload}


def _campos_obrigatorios_ausentes(payload):
	return sorted(campo for campo in CAMPO_OBRIGATORIOS if not payload.get(campo))


def _erro(mensagem, status_code):
	resposta = jsonify({"erro": mensagem})
	resposta.status_code = status_code
	return resposta


app = create_app()


if __name__ == "__main__":
	porta = int(os.getenv("PORT", "5000"))
	serve(app, host="0.0.0.0", port=porta)