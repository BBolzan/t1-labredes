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

- podman network create lab
- podman network ls

### Executando múltiplas instâncias

Executar as intâncias em terminais separados na máquina *host*. Isso deve ser feito para que as mesmas possam ser finalizadas individualmente (com Ctrl+C).

- podman run --cap-add NET_ADMIN --privileged --network lab -p 8080:8080 labredes
- podman run --cap-add NET_ADMIN --privileged --network lab -p 8081:8080 labredes
- podman run --cap-add NET_ADMIN --privileged --network lab -p 8082:8080 labredes

Abrir um browser no *host* e acessar as URL "localhost:8080", "localhost:8081" ... para acessar cada container.
