# Lista M3U FAST BR para SS IPTV

Projeto que **monta automaticamente uma lista `.m3u`** com canais gratuitos
(FAST) de **Pluto TV**, **Plex**, **Samsung TV Plus** e **Roku Channel**
(interpretado como "Runtime"), pronta para usar no **SS IPTV** e em qualquer
player que aceite M3U (VLC, Kodi, TiviMate etc.).

Um workflow do GitHub Actions **busca os canais a cada 6 horas** e atualiza a
lista sozinho — sem servidor e sem custo.

## Provedores incluidos

| Provedor | Grupo na lista | Brasil? |
|---|---|---|
| Pluto TV | `Pluto TV BR` | **Sim** — feed `br` dedicado (~179 canais em portugues) |
| Plex | `Plex` | Nao expoe feed `br` nesta fonte (padrao: `mx`) |
| Samsung TV Plus | `Samsung TV Plus` | Nao expoe feed `br` nesta fonte (padrao: `us`) |
| Roku Channel ("Runtime") | `Roku (Runtime)` | Catalogo unico, sem regiao (majoritariamente US) |

> **Sobre "Runtime":** nao existe um servico FAST amplamente conhecido com esse
> nome exato. Interpretei como **Roku Channel**. Se voce quis dizer outro
> servico (ex.: Rakuten), e so trocar/adicionar um bloco no
> [`config.yml`](config.yml).
>
> **Sobre o Brasil:** entre esses servicos, apenas a **Pluto TV** disponibiliza
> publicamente um feed brasileiro gratuito. Plex, Samsung TV Plus e Roku nao
> expoem um feed `br` nesta fonte gratuita, entao foram incluidos com regioes
> proximas (configuraveis). Se voce encontrar um feed `.m3u` BR de algum deles,
> basta adicionar um bloco `type: m3u` no `config.yml` (ja ha um exemplo).

## Como funciona

1. O script [`generate.py`](generate.py) le o [`config.yml`](config.yml).
2. Para cada provedor, busca a lista de canais na fonte open-source
   `matthuisman/i.mjh.nz` (nome, logo, grupo e EPG) e monta a URL de stream via
   o redirecionador `jmp2.uk`, que resolve para o stream oficial do servico no
   momento do play (metodo atual que funciona apos as mudancas de 2024).
3. Aplica filtros, remove canais duplicados e grava:
   - `playlists/lista.m3u` — **lista combinada** (todos os provedores);
   - `playlists/pluto-tv-br.m3u`, `playlists/plex.m3u`, etc. — uma por provedor.
4. O GitHub Actions roda esse processo **a cada 6 horas** e faz commit da lista.

## Como usar (passo a passo)

### 1. Suba o projeto no GitHub

```bash
git init
git add .
git commit -m "primeiro commit"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/SEU_REPO.git
git push -u origin main
```

### 2. Habilite as permissoes do Actions

No repositorio: **Settings -> Actions -> General -> Workflow permissions** ->
marque **Read and write permissions** -> **Save**.
Isso permite que o robo faca commit da lista atualizada.

### 3. Gere a primeira lista

Va em **Actions -> "Atualizar lista M3U" -> Run workflow**.
Ao terminar, os arquivos aparecem na pasta `playlists/`.

### 4. Pegue o link RAW e coloque no SS IPTV

O link da sua lista combinada sera:

```
https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/playlists/lista.m3u
```

No **SS IPTV**:

1. Abra o app e va em **Configuracoes (Settings)**.
2. Aba **Listas de reproducao / Content -> Playlists**.
3. Clique em **Adicionar**, de um nome e cole o link RAW acima.
4. Salve e volte para a tela inicial — os canais aparecem em **Minha lista**.

> A lista inclui `url-tvg` com os guias de programacao (EPG) de cada provedor,
> entao o SS IPTV tambem pode exibir a programacao dos canais.

## Rodar localmente (opcional)

```bash
pip install -r requirements.txt
python generate.py --config config.yml
```

Resultado em `playlists/lista.m3u`.

## Personalizar ([`config.yml`](config.yml))

- **Ativar/desativar** um provedor: `enabled: true|false`.
- **Mudar regiao**: edite `regions` (ex.: `regions: [br]`, `regions: [us, mx]`).
- **Filtrar por nome do canal**:
  - `include: ["news", "filmes"]` mantem apenas canais com esses termos;
  - `exclude: ["24/7", "teste"]` remove canais com esses termos.
- **Filtros globais** (`global_filters`) valem para todos os provedores.
- **Adicionar uma fonte M3U propria**: use um bloco `type: m3u` com a URL do
  feed (ha um exemplo pronto, desligado, no final do arquivo).
- **Mudar a frequencia**: edite o `cron` em
  [`.github/workflows/update-playlist.yml`](.github/workflows/update-playlist.yml).
  Ex.: `0 */6 * * *` = a cada 6 horas; `0 */3 * * *` = a cada 3 horas.

## Estrutura

```
.
|- generate.py                            # gerador da lista
|- config.yml                             # provedores, regioes e filtros
|- requirements.txt                       # dependencias Python
|- playlists/                             # listas .m3u geradas
|- .github/workflows/update-playlist.yml  # automacao a cada 6 horas
```

## Aviso legal

Este projeto **nao hospeda nem redistribui conteudo**. Ele apenas organiza
links de canais gratuitos (FAST) ja disponibilizados publicamente pelos
respectivos servicos. Use de acordo com os termos de cada provedor e com a
legislacao local.

## Creditos

- Metadados de canais e EPG: [matthuisman/i.mjh.nz](https://github.com/matthuisman/i.mjh.nz)

## Licenca

[MIT](LICENSE)
