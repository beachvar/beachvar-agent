# BeachVar Agent

Serviço de auto-atualização para dispositivos BeachVar. Monitora o GitHub Container Registry e atualiza automaticamente os containers `beachvar-device` e `beachvar-agent`.

## Funcionalidades

- Verifica periodicamente novas versões das imagens Docker
- Atualiza automaticamente o `beachvar-device`
- Auto-atualização do próprio agent
- Reporta versões ao backend para monitoramento
- Obtém token do registry dinamicamente do backend

## Instalação no Device

### 1. Pré-requisitos

```bash
# Instalar Docker (se ainda não tiver)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Criar diretórios
sudo mkdir -p /etc/beachvar
```

### 2. Configurar SSH para terminal web

```bash
# Criar usuário 'device' com permissão sudo
sudo useradd -m -s /bin/bash -G sudo device

# Permitir sudo sem senha
echo "device ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/device
sudo chmod 440 /etc/sudoers.d/device

# Gerar chave SSH
sudo -u device ssh-keygen -t ed25519 -f /home/device/.ssh/id_ed25519 -N ""

# Configurar authorized_keys
sudo -u device bash -c 'cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys'
sudo chmod 600 /home/device/.ssh/authorized_keys

# Copiar chave para local acessível pelo Docker
sudo cp /home/device/.ssh/id_ed25519 /etc/beachvar/ssh_key
sudo chmod 644 /etc/beachvar/ssh_key
```

### 3. Criar arquivo de configuração

Obtenha o `DEVICE_TOKEN` no admin do backend.

```bash
sudo nano /etc/beachvar/.env
```

Conteúdo (apenas 2 variáveis necessárias):
```env
DEVICE_TOKEN=seu_token_aqui
BACKEND_URL=https://beachvar-api.cainelli.xyz
```

**Nota:** O `GATEWAY_URL` e `DEVICE_ID` são obtidos automaticamente do backend via `/api/device/config/`.

### 4. Criar docker-compose.yml

```bash
sudo nano /etc/beachvar/docker-compose.yml
```

Conteúdo:
```yaml
services:
  device:
    image: ghcr.io/beachvar/beachvar-device:latest
    container_name: beachvar-device
    command: python -O main.py
    env_file:
      - .env
    environment:
      - SSH_HOST=localhost
      - SSH_USER=device
      - SSH_PORT=22
      - SSH_KEY_PATH=/ssh/id_ed25519
    volumes:
      - /etc/beachvar/ssh_key:/ssh/id_ed25519.mount:ro
    restart: unless-stopped
    network_mode: host

  agent:
    image: ghcr.io/beachvar/beachvar-agent:latest
    container_name: beachvar-agent
    env_file:
      - .env
    environment:
      - CHECK_INTERVAL_SECONDS=300
      - COMPOSE_FILE_PATH=/etc/beachvar/docker-compose.yml
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/beachvar:/etc/beachvar:ro
      - beachvar-versions:/etc/beachvar-agent
    restart: unless-stopped
    depends_on:
      - device

volumes:
  beachvar-versions:
```

### 5. Iniciar os serviços

```bash
cd /etc/beachvar
sudo docker compose pull
sudo docker compose up -d
```

### 6. Verificar status

```bash
# Ver logs do device
sudo docker logs -f beachvar-device

# Ver logs do agent
sudo docker logs -f beachvar-agent

# Ver status
sudo docker compose ps
```

## Comando de instalação rápida

```bash
# 1. Setup SSH (rodar uma vez)
sudo mkdir -p /etc/beachvar && \
sudo useradd -m -s /bin/bash -G sudo device 2>/dev/null || true && \
echo "device ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/device && \
sudo chmod 440 /etc/sudoers.d/device && \
sudo -u device ssh-keygen -t ed25519 -f /home/device/.ssh/id_ed25519 -N "" 2>/dev/null || true && \
sudo -u device bash -c 'cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys' && \
sudo chmod 600 /home/device/.ssh/authorized_keys && \
sudo cp /home/device/.ssh/id_ed25519 /etc/beachvar/ssh_key && \
sudo chmod 644 /etc/beachvar/ssh_key && \
echo "SSH configurado!"

# 2. Criar .env (substitua SEU_TOKEN)
cat << 'EOF' | sudo tee /etc/beachvar/.env
DEVICE_TOKEN=SEU_TOKEN
BACKEND_URL=https://beachvar-api.cainelli.xyz
EOF

# 3. Criar docker-compose.yml
cat << 'EOF' | sudo tee /etc/beachvar/docker-compose.yml
services:
  device:
    image: ghcr.io/beachvar/beachvar-device:latest
    container_name: beachvar-device
    command: python -O main.py
    env_file: [.env]
    environment: [SSH_HOST=localhost, SSH_USER=device, SSH_PORT=22, SSH_KEY_PATH=/ssh/id_ed25519]
    volumes: [/etc/beachvar/ssh_key:/ssh/id_ed25519.mount:ro]
    restart: unless-stopped
    network_mode: host

  agent:
    image: ghcr.io/beachvar/beachvar-agent:latest
    container_name: beachvar-agent
    env_file: [.env]
    environment: [CHECK_INTERVAL_SECONDS=300, COMPOSE_FILE_PATH=/etc/beachvar/docker-compose.yml]
    volumes: [/var/run/docker.sock:/var/run/docker.sock, /etc/beachvar:/etc/beachvar:ro, beachvar-versions:/etc/beachvar-agent]
    restart: unless-stopped

volumes:
  beachvar-versions:
EOF

# 4. Iniciar
cd /etc/beachvar && sudo docker compose pull && sudo docker compose up -d
```

## Variáveis de Ambiente

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `DEVICE_TOKEN` | Token de autenticação do device | - |
| `BACKEND_URL` | URL da API backend | `https://beachvar-api.cainelli.xyz` |
| `CHECK_INTERVAL_SECONDS` | Intervalo de verificação | `300` (5 min) |
| `COMPOSE_FILE_PATH` | Caminho do docker-compose.yml | `/etc/beachvar/docker-compose.yml` |
| `LOG_LEVEL` | Nível de log | `INFO` |

## Endpoints usados pelo Agent

- `GET /api/device/registry-token/` - Obtém token do GitHub registry
- `GET /api/device/config/` - Obtém configuração (gateway_url, device_id)
- `POST /api/device/version/` - Reporta versões das imagens

## Como funciona

1. Agent inicia e obtém token do registry via `/api/device/registry-token/`
2. Faz login no ghcr.io com o token
3. A cada 5 minutos, verifica se há novas versões
4. Se houver, faz pull e reinicia o container
5. Reporta versões ao backend via `/api/device/version/`

## Desenvolvimento

```bash
# Instalar dependências
uv pip install -e .

# Rodar localmente
python main.py
```
