.PHONY: build-env
build-venv:
	python3 -m venv .

.PHONY: install
install:
	. bin/activate && pip install --upgrade pip
	. bin/activate && pip install setuptools wheel
	. bin/activate && pip install -r requirements.txt
