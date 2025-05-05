#!/usr/bin/env python3
import socket
import time
import threading
import sys
import random
import os
import base64
import hashlib
from datetime import datetime

# Configuração
UDP_PORT = 5000
BROADCAST_ADDR = '255.255.255.255'
HEARTBEAT_INTERVAL = 25
DEVICE_TIMEOUT = 120
ACK_TIMEOUT = 2
MAX_RETRIES = 10
CHUNK_SIZE = 250

# Estado global
device_name = ""
known_devices = {}  # {nome: (ip, porta, última_vez_visto)}
running = True
received_ids = set()  # IDs de mensagens já recebidas
ack_received = {}  # {id_mensagem: bool} - Para rastrear ACKs recebidos

# Estado para transferência de arquivos
pending_files = {}  # {id_arquivo: (nome_arquivo, tamanho_total, chunks_recebidos, origem)}
file_chunks = {}  # {id_arquivo: {seq: dados}}

# Locks
devices_lock = threading.Lock()
ack_lock = threading.Lock()

def generate_message_id():
    """Gera um ID único para mensagens."""
    return f"{device_name}-{int(time.time())}-{random.randint(1000, 9999)}"

def calculate_file_hash(file_path):
    """Calcula o hash SHA-256 de um arquivo."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def send_heartbeat():
    """Enviar mensagem de heartbeat para todos os dispositivos na rede."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    
    while running:
        try:
            message = f"HEARTBEAT {device_name}"
            sock.sendto(message.encode(), (BROADCAST_ADDR, UDP_PORT))
            print(f"Enviado heartbeat às {datetime.now().strftime('%H:%M:%S')}")
            time.sleep(HEARTBEAT_INTERVAL)
        except Exception as e:
            print(f"Erro ao enviar heartbeat: {e}")
            time.sleep(1)

def listen_for_messages():
    """Escutar mensagens recebidas na porta principal."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', UDP_PORT))
    print(f"Escutando na porta principal {UDP_PORT}")
    
    while running:
        try:
            data, addr = sock.recvfrom(8192)  # Buffer maior para chunks
            message = data.decode().strip()
            handle_message(message, addr)
        except Exception as e:
            print(f"Erro ao receber mensagem na porta principal: {e}")

def send_message_to_ip(ip, port, message):
    """Envia uma mensagem para um IP específico."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bytes_sent = sock.sendto(message.encode(), (ip, port))
        sock.close()
        return bytes_sent > 0
    except Exception as e:
        print(f"Erro ao enviar mensagem para {ip}:{port}: {e}")
        return False

def handle_message(message, addr):
    """Processa mensagens recebidas."""
    parts = message.split(maxsplit=3)
    
    if len(parts) < 1:
        return
    
    message_type = parts[0]
    ip, port = addr
    
    if message_type == "HEARTBEAT" and len(parts) >= 2:
        device_name_received = parts[1]
        # Não processar nosso próprio heartbeat
        if device_name_received != device_name:
            current_time = time.time()
            
            # Atualizar ou adicionar dispositivo a dispositivos conhecidos
            with devices_lock:
                known_devices[device_name_received] = (ip, port, current_time)
            print(f"Recebido heartbeat de {device_name_received} em {ip}:{port}")
    
    elif message_type == "TALK" and len(parts) >= 3:
        # TALK <id> <dados>
        message_id = parts[1]
        content = parts[2]
        
        # Verificar se já recebemos esta mensagem
        if message_id in received_ids:
            print(f"Mensagem duplicada {message_id}, enviando ACK novamente")
            # Enviar ACK mesmo para mensagens duplicadas
            ack_message = f"ACK {message_id}"
            send_message_to_ip(ip, UDP_PORT, ack_message)
            return
        
        # Marcar como recebida
        received_ids.add(message_id)
        
        # Identificar o remetente
        sender = "Dispositivo desconhecido"
        with devices_lock:
            for name, (dev_ip, _, _) in known_devices.items():
                if dev_ip == ip:
                    sender = name
                    break
        
        # Exibir a mensagem de forma destacada
        print(f"\n===== NOVA MENSAGEM =====")
        print(f"De: {sender}")
        print(f"Mensagem: {content}")
        print(f"========================\n")
        
        # Enviar ACK
        ack_message = f"ACK {message_id}"
        send_message_to_ip(ip, UDP_PORT, ack_message)
    
    elif message_type == "FILE" and len(parts) >= 4:
        # FILE <id> <nome-arquivo> <tamanho>
        file_id = parts[1]
        filename = parts[2]
        try:
            file_size = int(parts[3])
        except ValueError:
            print(f"Tamanho de arquivo inválido: {parts[3]}")
            return
        
        # Verificar se já estamos recebendo este arquivo
        if file_id in pending_files:
            print(f"Já estamos recebendo o arquivo {file_id}, enviando ACK novamente")
            send_message_to_ip(ip, UDP_PORT, f"ACK {file_id}")
            return
        
        # Identificar o remetente
        sender = "Dispositivo desconhecido"
        with devices_lock:
            for name, (dev_ip, _, _) in known_devices.items():
                if dev_ip == ip:
                    sender = name
                    break
        
        # Iniciar recebimento do arquivo
        print(f"\n===== RECEBENDO ARQUIVO =====")
        print(f"De: {sender}")
        print(f"Arquivo: {filename}")
        print(f"Tamanho: {file_size} bytes")
        print(f"=========================\n")
        
        # Inicializar estruturas para este arquivo
        file_chunks[file_id] = {}
        pending_files[file_id] = (filename, file_size, 0, sender)
        
        # Enviar ACK para iniciar a transferência
        send_message_to_ip(ip, UDP_PORT, f"ACK {file_id}")
    
    elif message_type == "CHUNK" and len(parts) >= 4:
        # CHUNK <id> <seq> <dados>
        file_id = parts[1]
        try:
            seq = int(parts[2])
        except ValueError:
            print(f"Número de sequência inválido: {parts[2]}")
            return
        
        data_b64 = parts[3]
        
        # Verificar se estamos esperando este arquivo
        if file_id not in pending_files:
            print(f"Recebido chunk para arquivo desconhecido {file_id}")
            return
        
        filename, file_size, chunks_received, sender = pending_files[file_id]
        
        # Verificar se já recebemos este chunk
        if seq in file_chunks[file_id]:
            print(f"Chunk duplicado {seq}, enviando ACK novamente")
            send_message_to_ip(ip, UDP_PORT, f"ACK {file_id}-{seq}")
            return
        
        # Processar o chunk
        try:
            chunk_data = base64.b64decode(data_b64)
            file_chunks[file_id][seq] = chunk_data
            
            # Atualizar progresso
            chunks_received += 1
            pending_files[file_id] = (filename, file_size, chunks_received, sender)
            
            # Calcular progresso
            total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
            progress = chunks_received / total_chunks * 100
            print(f"Recebido chunk {seq+1}/{total_chunks} ({progress:.1f}%)")
            
            # Enviar ACK para este chunk específico
            chunk_ack_id = f"{file_id}-{seq}"
            send_message_to_ip(ip, UDP_PORT, f"ACK {chunk_ack_id}")
        except Exception as e:
            print(f"Erro ao processar chunk: {e}")
    
    elif message_type == "END" and len(parts) >= 3:
        # END <id> <hash>
        file_id = parts[1]
        received_hash = parts[2]
        
        # Verificar se estamos esperando este arquivo
        if file_id not in pending_files:
            print(f"Recebido END para arquivo desconhecido {file_id}")
            return
        
        filename, file_size, chunks_received, sender = pending_files[file_id]
        
        try:
            # Salvar o arquivo na pasta /root
            output_path = f"/root/{filename}"
            
            # Reconstruir o arquivo a partir dos chunks
            with open(output_path, "wb") as f:
                # Ordenar os chunks por número de sequência
                for seq in sorted(file_chunks[file_id].keys()):
                    f.write(file_chunks[file_id][seq])
            
            # Verificar integridade do arquivo
            calculated_hash = calculate_file_hash(output_path)
            
            if calculated_hash != received_hash:
                print(f"ERRO: Hash do arquivo não corresponde!")
                print(f"Esperado: {received_hash}")
                print(f"Calculado: {calculated_hash}")
                
                # Remover arquivo corrompido
                os.remove(output_path)
                
                # Enviar NACK com motivo
                send_message_to_ip(ip, UDP_PORT, f"NACK {file_id} hash_invalido")
                
                # Limpar recursos
                del pending_files[file_id]
                del file_chunks[file_id]
                return
            
            # Transferência bem-sucedida
            print(f"\n===== ARQUIVO RECEBIDO =====")
            print(f"De: {sender}")
            print(f"Arquivo: {filename}")
            print(f"Tamanho: {file_size} bytes")
            print(f"Salvo em: {output_path}")
            print(f"Hash validado com sucesso!")
            print(f"==========================\n")
            
            # Enviar ACK final
            send_message_to_ip(ip, UDP_PORT, f"ACK {file_id}")
            
            # Limpar recursos
            del pending_files[file_id]
            del file_chunks[file_id]
        except Exception as e:
            print(f"Erro ao finalizar arquivo: {e}")
            send_message_to_ip(ip, UDP_PORT, f"NACK {file_id} erro_processamento")
    
    elif message_type == "ACK":
        # ACK <id> ou ACK <id>-<seq>
        ack_id = parts[1]
        print(f"Recebido ACK para {ack_id} de {ip}:{port}")
        
        # Registrar que recebemos o ACK
        with ack_lock:
            ack_received[ack_id] = True
    
    elif message_type == "NACK" and len(parts) >= 3:
        # NACK <id> <motivo>
        nack_id = parts[1]
        motivo = parts[2]
        print(f"Recebido NACK para {nack_id}: {motivo}")
        
        # Marcar como falha
        with ack_lock:
            ack_received[nack_id] = False

def clean_inactive_devices():
    """Remover dispositivos que não enviaram heartbeat recentemente."""
    while running:
        try:
            current_time = time.time()
            # Criar uma cópia porque modificaremos o dict durante a iteração
            with devices_lock:
                devices_copy = known_devices.copy()
            
            for name, (ip, port, last_seen) in devices_copy.items():
                if current_time - last_seen > DEVICE_TIMEOUT:
                    print(f"Dispositivo {name} em {ip}:{port} está inativo, removendo")
                    with devices_lock:
                        if name in known_devices:
                            del known_devices[name]
            
            time.sleep(1)  # Verificar a cada segundo
        except Exception as e:
            print(f"Erro ao limpar dispositivos inativos: {e}")
            time.sleep(1)

def wait_for_ack(ack_id, timeout=ACK_TIMEOUT):
    """Espera por um ACK específico com timeout."""
    start_time = time.time()
    
    # Limpar qualquer ACK anterior com este ID
    with ack_lock:
        if ack_id in ack_received:
            del ack_received[ack_id]
    
    # Esperar pelo ACK
    while time.time() - start_time < timeout:
        with ack_lock:
            if ack_id in ack_received:
                return ack_received[ack_id]  # True para ACK, False para NACK
        time.sleep(0.1)  # Pequena pausa para não sobrecarregar CPU
    
    return None  # Timeout

def talk_to_device(target_device, content):
    """Envia uma mensagem para um dispositivo específico com confirmação."""
    with devices_lock:
        if target_device not in known_devices:
            print(f"Dispositivo {target_device} não encontrado.")
            return False
        
        ip, _, _ = known_devices[target_device]
    
    # Gerar ID único para a mensagem
    message_id = generate_message_id()
    
    # Preparar a mensagem
    message = f"TALK {message_id} {content}"
    
    # Tentar enviar com retransmissão
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"Enviando mensagem para {target_device} (tentativa {attempt}/{MAX_RETRIES})...")
        
        if send_message_to_ip(ip, UDP_PORT, message):
            # Esperar pelo ACK
            result = wait_for_ack(message_id)
            
            if result is True:  # ACK recebido
                print(f"Mensagem entregue com sucesso para {target_device}!")
                return True
            elif result is False:  # NACK recebido
                print(f"Mensagem rejeitada por {target_device}.")
                return False
        
        if attempt < MAX_RETRIES:
            print(f"Sem confirmação, tentando novamente...")
            time.sleep(1)
    
    print(f"Falha ao entregar mensagem para {target_device} após {MAX_RETRIES} tentativas.")
    return False

def send_file_to_device(target_device, file_path):
    """Inicia o envio de um arquivo para um dispositivo."""
    # Verificar se o arquivo existe
    if not os.path.isfile(file_path):
        print(f"Arquivo não encontrado: {file_path}")
        return False
    
    # Verificar se o dispositivo existe
    with devices_lock:
        if target_device not in known_devices:
            print(f"Dispositivo {target_device} não encontrado.")
            return False
        
        ip, _, _ = known_devices[target_device]
    
    # Iniciar a transferência em uma thread separada
    transfer_thread = threading.Thread(
        target=transfer_file,
        args=(target_device, ip, file_path)
    )
    transfer_thread.daemon = True
    transfer_thread.start()
    
    return True

def transfer_file(target_device, ip, file_path):
    """Gerencia a transferência completa de um arquivo com confirmação de recebimento."""
    try:
        # Obter informações do arquivo
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        # Gerar ID único para o arquivo
        file_id = generate_message_id()
        
        print(f"\nIniciando transferência de arquivo:")
        print(f"- Dispositivo destino: {target_device}")
        print(f"- IP destino: {ip}")
        print(f"- Arquivo: {file_name}")
        print(f"- Tamanho: {file_size} bytes")
        
        # 1. Enviar mensagem FILE
        file_message = f"FILE {file_id} {file_name} {file_size}"
        
        # Tentar enviar FILE até receber ACK ou esgotar tentativas
        for attempt in range(1, MAX_RETRIES + 1):
            print(f"Enviando solicitação de transferência (tentativa {attempt}/{MAX_RETRIES})...")
            
            if send_message_to_ip(ip, UDP_PORT, file_message):
                # Esperar pelo ACK
                result = wait_for_ack(file_id)
                
                if result is True:  # ACK recebido
                    print("Solicitação aceita! Iniciando transferência...")
                    break
                elif result is False:  # NACK recebido
                    print(f"Solicitação rejeitada por {target_device}.")
                    return False
            
            if attempt < MAX_RETRIES:
                print("Sem confirmação, tentando novamente...")
                time.sleep(1)
            else:
                print(f"Transferência rejeitada após {MAX_RETRIES} tentativas.")
                return False
        
        # Calcular o número total de chunks
        total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE  # Arredondar para cima
        print(f"O arquivo será enviado em {total_chunks} chunks de {CHUNK_SIZE} bytes cada.")
        
        # 2. Enviar chunks
        with open(file_path, "rb") as f:
            for seq in range(total_chunks):
                # Ler o próximo chunk
                chunk_data = f.read(CHUNK_SIZE)
                if not chunk_data:
                    break
                
                # Codificar o chunk
                chunk_b64 = base64.b64encode(chunk_data).decode()
                
                # Enviar chunk e aguardar ACK
                chunk_message = f"CHUNK {file_id} {seq} {chunk_b64}"
                chunk_ack_id = f"{file_id}-{seq}"
                
                # Tentar enviar CHUNK até receber ACK ou esgotar tentativas
                for attempt in range(1, MAX_RETRIES + 1):
                    print(f"Enviando chunk {seq+1}/{total_chunks} (tentativa {attempt}/{MAX_RETRIES})...")
                    
                    if send_message_to_ip(ip, UDP_PORT, chunk_message):
                        # Esperar pelo ACK para este chunk específico
                        result = wait_for_ack(chunk_ack_id)
                        
                        if result is True:  # ACK recebido
                            break
                        elif result is False:  # NACK recebido
                            print(f"Chunk rejeitado por {target_device}.")
                            # Continuar tentando
                    
                    if attempt < MAX_RETRIES:
                        print("Sem confirmação, tentando novamente...")
                        time.sleep(1)
                    else:
                        print(f"Falha ao enviar chunk {seq+1} após {MAX_RETRIES} tentativas.")
                        return False
                
                # Calcular progresso
                progress = (seq + 1) / total_chunks * 100
                print(f"Progresso: {progress:.1f}%")
        
        # 3. Enviar END com hash
        file_hash = calculate_file_hash(file_path)
        end_message = f"END {file_id} {file_hash}"
        
        # Tentar enviar END até receber ACK ou esgotar tentativas
        for attempt in range(1, MAX_RETRIES + 1):
            print(f"Enviando confirmação final (END) (tentativa {attempt}/{MAX_RETRIES})...")
            
            if send_message_to_ip(ip, UDP_PORT, end_message):
                # Esperar pelo ACK final
                result = wait_for_ack(file_id)
                
                if result is True:  # ACK recebido
                    print(f"Transferência do arquivo {file_name} concluída com sucesso!")
                    return True
                elif result is False:  # NACK recebido
                    print(f"Verificação de hash falhou no dispositivo {target_device}.")
                    return False
            
            if attempt < MAX_RETRIES:
                print("Sem confirmação, tentando novamente...")
                time.sleep(1)
            else:
                print(f"Falha na confirmação final após {MAX_RETRIES} tentativas.")
                return False
    
    except Exception as e:
        print(f"Erro durante a transferência do arquivo: {e}")
        return False

def show_active_devices():
    """Exibir dispositivos atualmente ativos."""
    print("\nDispositivos Ativos:")
    print("-" * 60)
    print(f"{'Nome':<20} {'Endereço IP':<15} {'Porta':<6} {'Visto há (s)':<10}")
    print("-" * 60)
    
    current_time = time.time()
    with devices_lock:
        if not known_devices:
            print("Nenhum dispositivo encontrado.")
        else:
            for name, (ip, port, last_seen) in known_devices.items():
                seconds_ago = int(current_time - last_seen)
                print(f"{name:<20} {ip:<15} {port:<6} {seconds_ago:<10}")
    
    print("-" * 60)

def command_loop():
    """Processar comandos do usuário."""
    global running
    
    while running:
        try:
            cmd = input("\nDigite o comando (devices, talk, sendfile, exit): ").strip()
            
            if cmd == "devices":
                show_active_devices()
            elif cmd.startswith("talk "):
                # Formato: talk <nome> <mensagem>
                parts = cmd.split(maxsplit=2)
                if len(parts) < 3:
                    print("Formato incorreto. Use: talk <nome> <mensagem>")
                else:
                    target_device = parts[1]
                    message = parts[2]
                    talk_to_device(target_device, message)
            elif cmd.startswith("sendfile "):
                # Formato: sendfile <nome> <caminho-arquivo>
                parts = cmd.split(maxsplit=2)
                if len(parts) < 3:
                    print("Formato incorreto. Use: sendfile <nome> <caminho-arquivo>")
                else:
                    target_device = parts[1]
                    file_path = parts[2]
                    send_file_to_device(target_device, file_path)
            elif cmd == "exit":
                running = False
                print("Desligando...")
                break
            else:
                print("Comando desconhecido. Comandos disponíveis: devices, talk, sendfile, exit")
        except KeyboardInterrupt:
            running = False
            break
        except Exception as e:
            print(f"Erro ao processar comando: {e}")

def main():
    """Função principal para executar a aplicação."""
    global device_name
    
    if len(sys.argv) > 1:
        device_name = sys.argv[1]
    else:
        device_name = input("Digite o nome do dispositivo: ")
    
    print(f"Iniciando dispositivo '{device_name}' na porta UDP {UDP_PORT}")
    
    # Iniciar threads
    threads = [
        threading.Thread(target=send_heartbeat),
        threading.Thread(target=listen_for_messages),
        threading.Thread(target=clean_inactive_devices)
    ]
    
    for thread in threads:
        thread.daemon = True
        thread.start()
    
    # Loop de comando na thread principal
    try:
        command_loop()
    except KeyboardInterrupt:
        pass
    finally:
        global running
        running = False
        print("\nDesligando...")
        
        # Esperar que as threads terminem
        for thread in threads:
            thread.join(timeout=1)

if __name__ == "__main__":
    main()