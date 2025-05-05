# Configuração do ambiente em containers para o LabRedes

## Gerenciamento de imagens

Para construir uma imagem, executar:

- podman build -t labredes .

Para listar imagens instaladas:

- podman image ls

Para remover a imagem (forçadamente):

- podman rmi labredes --force


## Gerenciamento de containers

Para listar containers em execução

- podman container ls

Para executar um comando remoto

- podman exec -it <container_name\> <command\>

Para copiar arquivos de um container

- podman cp <container_name\>:/container/file/path/ /host/path/target


## Carregando uma instância

Em um terminal da máquina *host*:

- podman run --cap-add NET_ADMIN --privileged -p 8080:8080 labredes

Abrir um browser no *host* e acessar a URL "localhost:8080".


## Rede com múltiplos containers

### Criando uma rede

- podman network create t1-lab
- podman network ls

### Executando múltiplas instâncias

Executar os containers em terminais separados na máquina *host* (para que possam ser finalizados individualmente com Ctrl+C):

```bash
# Container 1
podman run -d --name device1 -v "$(pwd):/root/T1" --cap-add NET_ADMIN --privileged --network t1-lab -p 8081:8080 ghcr.io/sjohann81/labredes

# Container 2
podman run -d --name device2 -v "$(pwd):/root/T1" --cap-add NET_ADMIN --privileged --network t1-lab -p 8082:8080 ghcr.io/sjohann81/labredes

# Container 3
podman run -d --name device3 -v "$(pwd):/root/T1" --cap-add NET_ADMIN --privileged --network t1-lab -p 8083:8080 ghcr.io/sjohann81/labredes
```

### Acessando os containers

Para acessar o terminal de cada container:

```bash
podman exec -it device1 /bin/bash
podman exec -it device2 /bin/bash
podman exec -it device3 /bin/bash
```

### Simulando perda de pacotes

Dentro do container, primeiro verifique a interface de rede:

```bash
ip link show
```

Abrir um browser no *host* e acessar as URLs:
- http://localhost:8081/
- http://localhost:8082/
- http://localhost:8083/