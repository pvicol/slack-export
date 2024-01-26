# =================================================
# Arquivo MAKEFILE para auxiliar o desenvolvedor.
# =================================================


# Monta o ambiente virtual
build-venv:
	python3 -m venv venv

# Instala o ambiente
install:
	@pip install --upgrade pip
	@pip install setuptools wheel
	@pip install -r requirements.txt