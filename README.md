# gmxflow web

Painel Flask/Peewee para criar e executar projetos do [gmxflow](https://github.com/MichelLacerda/gmxflow). Os projetos usam UUID e ficam em `PROJECT_ROOT/<uuid do usuário>/<uuid do projeto>`. Os arquivos enviados mantêm seus nomes originais na pasta `inputs/` de cada projeto. Os dados completos da configuração ficam no SQLite e o `config.toml` é gerado a partir deles a cada salvamento.

## Desenvolvimento no distrobox

```bash
distrobox enter devel
cd /var/home/kratos/Devel/gmxflow-web
uv sync
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
uv run flask --app src:create_app run --debug
```

Em outro terminal do mesmo distrobox, execute `uv run python -m src.worker`. O pacote gmxflow é instalado pelo uv a partir de `../gmxflow`; o código original não é alterado. GROMACS precisa estar instalado para executar simulações reais.

## Docker

Copie `.env.example` para `.env`, substitua `SECRET_KEY` por um valor aleatório e execute `docker compose up --build` neste diretório. A imagem instala GROMACS e instala o gmxflow local com uv. O contexto de build é o diretório pai para incluir o código original sem editá-lo. O volume `gmxflow_data` persiste banco, projetos e logs.

Uma instância do worker consome a fila SQLite. Um bloqueio no volume impede duas instâncias do worker de executar ao mesmo tempo. Projetos com falha, após correção e novo envio, recebem prioridade sobre projetos comuns. Se o worker morrer durante uma execução, o projeto é marcado como falho na próxima inicialização e os logs permanecem para inspeção.

O formulário exige PDB do receptor e do ligante; para `small_molecule`, exige também MOL2 e STR. Na edição, arquivos já enviados podem ser reutilizados enquanto existirem em `inputs/`. Ao salvar, o painel confere esses arquivos e valida sintaxe e parâmetros com `gmxflow validate`. A viabilidade da simulação é conferida na execução por `gmxflow run --strict-inputs`. O perfil `smoke` serve apenas para testar a pipeline.

Campo de força, modelo de água, tipo de caixa, perfil de simulação, motor, política de GPU e pinning usam seletores. Os nomes de íons e grupos de análise continuam livres porque dependem da topologia e dos grupos de índice de cada projeto. Configurações antigas com um campo de força personalizado continuam editáveis sem perder o valor salvo.

## Traduções

A interface usa Flask-Babel e catálogos gettext em `src/translations/`. Português brasileiro é o idioma padrão; o usuário pode alternar entre PT e EN no menu. Para atualizar os catálogos após mudar textos marcados com `_()`:

```bash
uv run pybabel extract -F babel.cfg -o src/translations/messages.pot .
uv run pybabel update -i src/translations/messages.pot -d src/translations
# Edite os arquivos messages.po de cada idioma.
uv run pybabel compile -d src/translations
```

Para adicionar outro idioma, use `uv run pybabel init -i src/translations/messages.pot -d src/translations -l CODIGO` e inclua o código na seleção de idioma em `create_app`.

## Verificações

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright
uv run pytest -q
```

O Ruff verifica estilo e problemas estáticos; o Pyright valida tipos com a `.venv` criada pelo uv, inclusive no Zed.
