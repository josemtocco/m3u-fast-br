#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de lista M3U para SS IPTV.

Monta uma lista .m3u combinando canais FAST (gratuitos) de varios provedores:
Pluto TV, Samsung TV Plus, Plex e Roku ("Runtime"). Tambem aceita qualquer
fonte M3U externa (type: m3u), para o caso de voce encontrar um feed BR
especifico de algum provedor.

Os metadados dos canais (nome, logo, grupo, EPG) vem do projeto open-source
`matthuisman/i.mjh.nz`, que e atualizado continuamente. Os streams usam o
redirecionador `jmp2.uk`, que resolve para o stream oficial de cada servico no
momento do play (metodo atual que funciona apos as mudancas de 2024).

Uso:
    python generate.py --config config.yml
"""
import argparse
import gzip
import json
import os
import re
import sys
import time
import uuid
import datetime

import requests
import yaml

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MJH = "https://github.com/matthuisman/i.mjh.nz/raw/refs/heads/master"
EXTINF_RE = re.compile(r'^#EXTINF:(-?\d+)\s*(.*?),(.*)$')
ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')


# --------------------------------------------------------------------------
# Download helpers
# --------------------------------------------------------------------------
def http_get(url, timeout=60, retries=3):
    headers = {"User-Agent": USER_AGENT}
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep((attempt + 1) * 5)
                continue
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1 + attempt)
    print(f"  [AVISO] falha ao baixar {url}: {last}", file=sys.stderr)
    return None


def get_json_gz(url):
    r = http_get(url)
    if not r:
        return None
    try:
        return json.loads(gzip.decompress(r.content))
    except OSError:
        return json.loads(r.content.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  [AVISO] JSON invalido em {url}: {exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------
# Channel container
# --------------------------------------------------------------------------
class Channel:
    __slots__ = ("cid", "name", "logo", "chno", "group", "url")

    def __init__(self, cid, name, url, logo="", chno=None, group=""):
        self.cid = cid
        self.name = name
        self.url = url
        self.logo = logo or ""
        self.chno = chno
        self.group = group or ""

    @property
    def key(self):
        return self.url.strip() or (self.cid, self.name)

    def render(self, group):
        attrs = [f'tvg-id="{self.cid}"']
        if self.chno is not None:
            attrs.append(f'tvg-chno="{self.chno}"')
        if self.logo:
            attrs.append(f'tvg-logo="{self.logo}"')
        attrs.append(f'group-title="{group}"')
        return f"#EXTINF:-1 {' '.join(attrs)},{self.name}\n{self.url}"


# --------------------------------------------------------------------------
# Provedores nativos
# --------------------------------------------------------------------------
def provider_pluto(regions):
    data = get_json_gz(f"{MJH}/PlutoTV/.channels.json.gz")
    out, epg = [], []
    if not data:
        return out, epg
    for region in regions:
        rdata = data.get("regions", {}).get(region)
        if not rdata:
            print(f"  [AVISO] Pluto TV nao possui a regiao '{region}'")
            continue
        epg.append(f"{MJH}/PlutoTV/{region}.xml.gz")
        for cid, ch in rdata.get("channels", {}).items():
            out.append(Channel(
                cid, ch.get("name", cid),
                f"https://jmp2.uk/plu-{cid}.m3u8",
                ch.get("logo", ""), ch.get("chno"), ch.get("group", ""),
            ))
    return out, epg


def provider_samsung(regions):
    data = get_json_gz(f"{MJH}/SamsungTVPlus/.channels.json.gz")
    out, epg = [], []
    if not data:
        return out, epg
    slug = data.get("slug", "stvp-{id}.m3u8")
    for region in regions:
        rdata = data.get("regions", {}).get(region)
        if not rdata:
            print(f"  [AVISO] Samsung TV Plus nao possui a regiao '{region}'")
            continue
        epg.append(f"{MJH}/SamsungTVPlus/{region}.xml.gz")
        for cid, ch in rdata.get("channels", {}).items():
            path = slug.replace("{id}", cid)
            out.append(Channel(
                cid, ch.get("name", cid),
                f"https://jmp2.uk/{path}",
                ch.get("logo", ""), ch.get("chno"), ch.get("group", ""),
            ))
    return out, epg


def _plex_token(region):
    cid = uuid.uuid4().hex
    headers = {
        "Accept": "application/json", "User-Agent": USER_AGENT,
        "X-Plex-Product": "Plex Web", "X-Plex-Version": "4.150.0",
        "X-Plex-Client-Identifier": cid, "X-Plex-Platform": "Web",
    }
    params = {"X-Plex-Product": "Plex Web", "X-Plex-Client-Identifier": cid}
    try:
        r = requests.post("https://clients.plex.tv/api/v2/users/anonymous",
                          headers=headers, params=params, timeout=20)
        r.raise_for_status()
        return r.json().get("authToken")
    except Exception as exc:  # noqa: BLE001
        print(f"  [AVISO] Plex: falha ao obter token: {exc}", file=sys.stderr)
        return None


def provider_plex(regions):
    data = get_json_gz(f"{MJH}/Plex/.channels.json.gz")
    out, epg = [], []
    if not data:
        return out, epg
    token = _plex_token(regions[0] if regions else "us")
    if not token:
        return out, epg
    want = set(regions)
    for region in regions:
        epg.append(f"{MJH}/Plex/{region}.xml.gz")
    for cid, ch in data.get("channels", {}).items():
        ch_regions = set(ch.get("regions", []))
        if want and not (want & ch_regions):
            continue
        out.append(Channel(
            cid, ch.get("name", cid),
            f"https://epg.provider.plex.tv/library/parts/{cid}/?X-Plex-Token={token}",
            ch.get("logo", ""), ch.get("chno"), ch.get("group", ""),
        ))
    return out, epg


def provider_roku(regions):  # noqa: ARG001 (Roku nao tem regioes)
    data = get_json_gz("https://i.mjh.nz/Roku/.channels.json")
    out, epg = [], []
    if not data:
        return out, epg
    epg.append("https://i.mjh.nz/Roku/all.xml.gz")
    for cid, ch in data.get("channels", {}).items():
        groups = ch.get("groups") or [""]
        out.append(Channel(
            cid, ch.get("name", cid),
            f"https://jmp2.uk/rok-{cid}.m3u8",
            ch.get("logo", ""), ch.get("chno"), groups[0],
        ))
    return out, epg


def provider_m3u(sources):
    """Fonte M3U externa generica (qualquer URL de lista .m3u/.m3u8)."""
    out = []
    for src in sources or []:
        r = http_get(src)
        if not r:
            continue
        lines = r.text.splitlines()
        pending = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXTINF"):
                m = EXTINF_RE.match(line)
                if m:
                    attrs = dict(ATTR_RE.findall(m.group(2)))
                    pending = (attrs, m.group(3).strip())
            elif line.startswith("#"):
                continue
            elif pending is not None:
                attrs, title = pending
                out.append(Channel(
                    attrs.get("tvg-id", ""), title, line,
                    attrs.get("tvg-logo", ""), attrs.get("tvg-chno"),
                    attrs.get("group-title", ""),
                ))
                pending = None
    return out, []


PROVIDERS = {
    "pluto": provider_pluto,
    "samsung": provider_samsung,
    "plex": provider_plex,
    "roku": provider_roku,
}


# --------------------------------------------------------------------------
# Filtros + escrita
# --------------------------------------------------------------------------
def matches(name, terms):
    low = name.lower()
    return any(t.lower() in low for t in terms if t)


def apply_filters(channels, inc, exc, g_inc, g_exc):
    res = []
    for ch in channels:
        if g_inc and not matches(ch.name, g_inc):
            continue
        if g_exc and matches(ch.name, g_exc):
            continue
        if inc and not matches(ch.name, inc):
            continue
        if exc and matches(ch.name, exc):
            continue
        res.append(ch)
    return res


def write_m3u(path, items, epg_attr=None):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = "#EXTM3U"
    if epg_attr:
        header += f' url-tvg="{epg_attr}"'
    out = [header, f"# Gerado automaticamente em {now}"]
    for group, ch in items:
        out.append(ch.render(group))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser(description="Gera lista M3U para SS IPTV")
    ap.add_argument("--config", default="config.yml")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    output_file = cfg.get("output_file", "playlists/lista.m3u")
    per_provider = cfg.get("generate_per_provider", True)
    gf = cfg.get("global_filters", {}) or {}
    g_inc = gf.get("include") or []
    g_exc = gf.get("exclude") or []

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

    seen = set()
    combined = []
    epg_all = []
    report = []

    for prov in cfg.get("providers", []):
        if not prov.get("enabled", True):
            continue
        name = prov.get("name", "Provedor")
        group = prov.get("group", name)
        ptype = prov.get("type", "")
        regions = prov.get("regions") or []
        print(f"==> {name} ({ptype})")

        if ptype in PROVIDERS:
            channels, epg = PROVIDERS[ptype](regions)
        elif ptype == "m3u":
            channels, epg = provider_m3u(prov.get("sources"))
        else:
            print(f"  [AVISO] tipo desconhecido: {ptype}")
            continue

        channels = apply_filters(
            channels, prov.get("include") or [], prov.get("exclude") or [],
            g_inc, g_exc,
        )

        unique = []
        for ch in channels:
            if ch.key in seen:
                continue
            seen.add(ch.key)
            unique.append(ch)

        combined.extend((group, ch) for ch in unique)
        epg_all.extend(epg)
        report.append((name, len(unique)))
        print(f"  {len(unique)} canais")

        if per_provider and unique:
            path = os.path.join(os.path.dirname(output_file),
                                f"{slugify(name)}.m3u")
            write_m3u(path, [(group, c) for c in unique],
                      ",".join(dict.fromkeys(epg)))
            print(f"  gravado {path}")

    write_m3u(output_file, combined, ",".join(dict.fromkeys(epg_all)))

    print("\n==== RESUMO ====")
    for name, n in report:
        print(f"  {name}: {n} canais")
    print(f"  TOTAL: {len(combined)} canais")
    print(f"  Arquivo: {output_file}")


if __name__ == "__main__":
    main()
