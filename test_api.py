import sqlite3
import pytest

from api import create_app


# ---------------------------------------------------------------------------
# FakeConnection / FakeCursor: sqlite3 emulando a interface mysql.connector
# ---------------------------------------------------------------------------

class _FakeCursor:
	def __init__(self, conn, dictionary=False):
		self._cur = conn.cursor()
		self._dictionary = dictionary
		self._lastrowid = None

	def execute(self, query, params=None):
		sqlite_query = query.replace("%s", "?")
		if params:
			self._cur.execute(sqlite_query, params)
		else:
			self._cur.execute(sqlite_query)
		self._lastrowid = self._cur.lastrowid

	def fetchall(self):
		rows = self._cur.fetchall()
		if self._dictionary and self._cur.description:
			cols = [d[0] for d in self._cur.description]
			return [dict(zip(cols, row)) for row in rows]
		return rows

	def fetchone(self):
		row = self._cur.fetchone()
		if row is None:
			return None
		if self._dictionary and self._cur.description:
			cols = [d[0] for d in self._cur.description]
			return dict(zip(cols, row))
		return row

	@property
	def lastrowid(self):
		return self._lastrowid

	def close(self):
		pass


class _FakeConnection:
	def __init__(self, sqlite_conn):
		self._conn = sqlite_conn

	def cursor(self, dictionary=False):
		return _FakeCursor(self._conn, dictionary=dictionary)

	def commit(self):
		self._conn.commit()

	def close(self):
		pass  # mantém viva durante o teste


def _criar_banco_teste():
	conn = sqlite3.connect(":memory:", check_same_thread=False)
	conn.execute("""
		CREATE TABLE imoveis (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			logradouro TEXT NOT NULL,
			tipo_logradouro TEXT,
			bairro TEXT,
			cidade TEXT NOT NULL,
			cep TEXT,
			tipo TEXT,
			valor REAL,
			data_aquisicao TEXT
		)
	""")
	conn.executemany(
		"INSERT INTO imoveis (logradouro,tipo_logradouro,bairro,cidade,cep,tipo,valor,data_aquisicao)"
		" VALUES (?,?,?,?,?,?,?,?)",
		[
			("Avenida Paulista", "Avenida", "Bela Vista", "Sao Paulo", "01311-000", "apartamento", 950000.0, "2024-01-10"),
			("Rua das Flores",  "Rua",     "Centro",    "Campinas",  "13010-000", "casa",        780000.0, "2023-07-22"),
			("Alameda Santos",  "Alameda", "Jardins",   "Sao Paulo",  "01419-002", "apartamento", 1100000.0, "2022-12-01"),
		],
	)
	conn.commit()
	return conn


@pytest.fixture
def app():
	sqlite_conn = _criar_banco_teste()
	fake = _FakeConnection(sqlite_conn)
	app = create_app(db_factory=lambda: fake)
	app.config["TESTING"] = True
	yield app
	sqlite_conn.close()


@pytest.fixture
def client(app):
	return app.test_client()


def test_listar_todos_os_imoveis(client):
	resposta = client.get("/imoveis")

	assert resposta.status_code == 200
	dados = resposta.get_json()
	assert len(dados) == 3
	assert dados[0].keys() == {
		"id",
		"logradouro",
		"tipo_logradouro",
		"bairro",
		"cidade",
		"cep",
		"tipo",
		"valor",
		"data_aquisicao",
	}


def test_busca_imovel_por_id(client):
	resposta = client.get("/imoveis/1")

	assert resposta.status_code == 200
	dados = resposta.get_json()
	assert dados["id"] == 1
	assert dados["cidade"] == "Sao Paulo"
	assert dados["tipo"] == "apartamento"


def test_retorna_404_quando_imovel_nao_existe(client):
	resposta = client.get("/imoveis/999")

	assert resposta.status_code == 404
	assert resposta.get_json() == {"erro": "Imovel nao encontrado"}


def test_criar_um_novo_imovel(client):
	payload = {
		"logradouro": "Rua Oscar Freire",
		"tipo_logradouro": "Rua",
		"bairro": "Pinheiros",
		"cidade": "Sao Paulo",
		"cep": "05409-010",
		"tipo": "casa",
		"valor": 1250000.0,
		"data_aquisicao": "2025-02-15",
	}

	resposta = client.post("/imoveis", json=payload)

	assert resposta.status_code == 201
	dados = resposta.get_json()
	assert dados["id"] == 4
	assert dados["logradouro"] == payload["logradouro"]
	assert resposta.headers["Location"] == "/imoveis/4"


def test_validar_campos_obrigatorios_na_criacao(client):
	resposta = client.post("/imoveis", json={"bairro": "Centro"})

	assert resposta.status_code == 400
	assert resposta.get_json() == {
		"erro": "Campos obrigatorios ausentes: cidade, logradouro"
	}


def test_atualizar_um_imovel_existente(client):
	resposta = client.put(
		"/imoveis/2",
		json={
			"cidade": "Valinhos",
			"tipo": "casa",
			"valor": 820000.0,
		},
	)

	assert resposta.status_code == 200
	dados = resposta.get_json()
	assert dados["id"] == 2
	assert dados["cidade"] == "Valinhos"
	assert dados["valor"] == 820000.0
	assert dados["logradouro"] == "Rua das Flores"


def test_remover_um_imovel_existente(client):
	resposta = client.delete("/imoveis/3")

	assert resposta.status_code == 204
	assert client.get("/imoveis/3").status_code == 404
	assert len(client.get("/imoveis").get_json()) == 2


def test_listar_imoveis_por_tipo(client):
	resposta = client.get("/imoveis/tipo/APARTAMENTO")

	assert resposta.status_code == 200
	dados = resposta.get_json()
	assert len(dados) == 2
	assert {item["logradouro"] for item in dados} == {
		"Avenida Paulista",
		"Alameda Santos",
	}


def test_listar_imoveis_por_cidade(client):
	resposta = client.get("/imoveis/cidade/sao paulo")

	assert resposta.status_code == 200
	dados = resposta.get_json()
	assert len(dados) == 2
	assert {item["tipo"] for item in dados} == {"apartamento"}