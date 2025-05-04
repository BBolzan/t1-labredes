@echo off
echo Iniciando ambiente de simulacao...
docker-compose down
docker-compose up -d

echo Esperando os conteineres iniciarem...
timeout /t 5

echo Abrindo navegadores para acesso aos conteineres...
start http://localhost:8080
start http://localhost:8081

echo Para executar o protocolo:
echo - Abra um terminal em cada contêiner
echo - Execute: python3 /root/T1/protocolo_udp.py dispositivo1
echo - No outro contêiner: python3 /root/T1/protocolo_udp.py dispositivo2

echo Para encerrar a simulacao:
echo docker-compose down