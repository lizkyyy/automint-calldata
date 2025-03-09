import os
import time
import requests
from web3 import Web3
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs

# Load environment variables
load_dotenv()

# Config
BLOCKVISION_API_KEY = os.getenv("BLOCKVISION_API_KEY", "2tqlLvpyrTlOilBAcWyYUU9Ezw0")  # Ganti jika ada API key baru
RPC_URL = "https://monad-testnet.g.alchemy.com/v2/D6h3ngNJ1IATsMMW0hMbzlxtpIsFKaTZ"
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
YOUR_ADDRESS = "YOURADDRESS"

# Opsi untuk mengaktifkan/menonaktifkan debug
DEBUG_ENABLED = True  # Ubah ke False untuk nonaktifkan debug

# Fungsi debug sederhana
def debug(msg):
    if DEBUG_ENABLED:
        print(f"[DEBUG] {msg}")

# Konek ke Monad Testnet via HTTP Alchemy
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    raise Exception("Gagal konek ke HTTP RPC!")
debug("Koneksi ke RPC berhasil")

# Setup account
account = w3.eth.account.from_key(PRIVATE_KEY)

# Fungsi buat ambil contract address dari link Magic Eden
def get_contract_address_from_magic_eden(magic_eden_url):
    try:
        # Parse URL untuk ekstrak path
        parsed_url = urlparse(magic_eden_url)
        path_parts = parsed_url.path.strip('/').split('/')
        
        # Cek apakah URL mengikuti format mint-terminal/<network>/<contract_address>
        if len(path_parts) >= 3 and path_parts[0] == "mint-terminal" and path_parts[1] == "monad-testnet":
            contract_address = path_parts[2]
            if w3.is_address(contract_address):
                return w3.to_checksum_address(contract_address)
            else:
                raise Exception("Alamat kontrak tidak valid dari Magic Eden")
        else:
            raise Exception("Format URL Magic Eden tidak valid")
    
    except Exception as e:
        raise Exception(f"Error mengekstrak alamat kontrak dari Magic Eden: {str(e)}")

# Fungsi buat ambil contract address secara manual atau dari Magic Eden
def get_contract_address():
    while True:
        choice = input("Pilih input (1 untuk manual, 2 untuk Magic Eden URL): ").strip()
        if choice == "1":
            addr = input("Masukkan contract address untuk sniping: ").strip()
            if w3.is_address(addr):
                return w3.to_checksum_address(addr)
            print("Error: Alamat tidak valid!")
        elif choice == "2":
            magic_eden_url = input("Masukkan URL Magic Eden (misalnya https://magiceden.io/mint-terminal/monad-testnet/0xca70d0d4...): ").strip()
            try:
                return get_contract_address_from_magic_eden(magic_eden_url)
            except Exception as e:
                print(f"Error: {str(e)}")
        else:
            print("Pilihan tidak valid, masukkan 1 atau 2!")

# Fungsi buat ambil tx_hash terbaru dari BlockVision dengan batasan 5 request per detik
def get_latest_tx_hash_from_blockvision(contract_address, timeout_seconds=10, api_timeout=20):
    start_time = time.time()
    request_count = 0
    max_requests = 50  # Batasi request lebih konservatif untuk 5 request/detik selama 10 detik = 50 request
    
    while time.time() - start_time < timeout_seconds and request_count < max_requests:
        try:
            base_url = "https://api.blockvision.org/v2/monad/account/transactions"
            headers = {
                "accept": "application/json",
                "x-api-key": BLOCKVISION_API_KEY
            }
            params = {
                "address": contract_address,
                "limit": 1,  # Ambil hanya 1 transaksi terbaru
            }
            
            # Hitung waktu antar request untuk memastikan 5 request/detik (delay 0.2 detik)
            time.sleep(0.2)  # Delay 0.2 detik untuk memastikan tidak melebihi 5 request/detik
            
            response = requests.get(base_url, headers=headers, params=params, timeout=api_timeout)
            
            if response.status_code == 403:
                raise Exception("Akses ditolak (403 Forbidden). Periksa API key, izin endpoint, atau parameter tambahan (misalnya chainId).")
            elif response.status_code == 429:
                debug("Rate limit tercapai (429), menunggu sebelum retry...")
                time.sleep(5)  # Delay lebih lama untuk rate limit
                continue
            elif response.status_code != 200:
                raise Exception(f"Error API: Status {response.status_code}")
            
            response.raise_for_status()
            transactions = response.json().get("result", {}).get("data", [])
            
            if not transactions:
                debug("Tidak ada transaksi ditemukan di BlockVision")
                request_count += 1
                continue
            
            # Ambil tx_hash terbaru
            tx = transactions[0]
            tx_hash = tx.get("hash", "")
            
            if not tx_hash or not tx_hash.startswith("0x"):
                debug("Tx hash tidak valid, coba lagi")
                request_count += 1
                continue
            
            debug(f"Tx hash terbaru ditemukan: {tx_hash}")
            return tx_hash

        except requests.RequestException as e:
            debug(f"Error dari BlockVision API: {str(e)} (status {response.status_code if 'response' in locals() else 'none'})")
            if "timed out" in str(e):
                debug("Timeout terjadi, mencoba lagi setelah delay...")
                time.sleep(2)  # Delay tambahan untuk retry setelah timeout
            request_count += 1
        except Exception as e:
            debug(f"Error memproses tx_hash: {str(e)}")
            time.sleep(1)
            request_count += 1

    raise Exception("Gagal menemukan tx_hash dari BlockVision setelah 10 detik atau melebihi batas request")

# Fungsi buat ambil calldata dari HTTP Alchemy menggunakan tx_hash
def get_caldata_from_rpc(tx_hash):
    try:
        debug(f"Mengakses RPC untuk tx_hash: {tx_hash}")
        
        # Ambil detail transaksi menggunakan HTTP RPC
        tx = w3.eth.get_transaction(tx_hash)
        
        if not tx or 'input' not in tx:
            raise Exception("Tidak dapat menemukan transaksi atau calldata di RPC")
        
        # Ekstrak calldata dan konversi jika perlu
        raw_input = tx['input']
        
        # Konversi bytes ke string hex jika input adalah bytes
        if isinstance(raw_input, bytes):
            caldata = "0x" + raw_input.hex()
        elif isinstance(raw_input, str):
            caldata = raw_input
        else:
            raise Exception("Format input dari RPC tidak didukung")
        
        debug(f"Caldata asli: {caldata}")
        
        # Validasi calldata sebelum diproses
        if not caldata or not isinstance(caldata, str) or len(caldata) < 10:
            raise Exception("Caldata tidak valid atau kosong dari RPC")
        
        # Modifikasi alamat penerima (asumsi parameter pertama adalah address)
        method_id = caldata[:10]
        new_address = w3.to_checksum_address(YOUR_ADDRESS)[2:].lower().zfill(64)
        remaining = caldata[74:] if len(caldata) > 74 else ""
        modified_caldata = f"{method_id}{new_address}{remaining}"

        # Validasi calldata final
        if not modified_caldata.startswith("0x") or len(modified_caldata) < 10:
            raise Exception("Caldata hasil modifikasi tidak valid")

        debug(f"Caldata dimodifikasi: {caldata}")
        return modified_caldata

    except Exception as e:
        raise Exception(f"Error memproses calldata: {str(e)}")

# Gas price agresif untuk sniping
def get_gas_price(attempt: int = 1):
    base_price = 50 + (attempt * 10)
    gas_price = min(w3.to_wei(base_price, "gwei"), w3.to_wei(100, "gwei"))
    return gas_price

# Gas limit
def get_gas_limit(caldata: str, value: int, contract_address: str):
    try:
        tx = {"to": contract_address, "from": account.address, "data": caldata, "value": value}
        return min(max(w3.eth.estimate_gas(tx), 50000), 150000)
    except Exception:
        return 100000

# Fungsi sniping
def snipe_mint(contract_address: str, value: int, max_attempts: int = 10):
    try:
        # Dapatkan tx_hash terbaru dari BlockVision
        tx_hash = get_latest_tx_hash_from_blockvision(contract_address)
        
        # Dapatkan calldata dari HTTP Alchemy menggunakan tx_hash
        caldata = get_caldata_from_rpc(tx_hash)
    except Exception as e:
        print(f"Error: {str(e)}")
        print("Bot tidak dapat memulai sniping karena gagal menemukan calldata otomatis.")
        return False

    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        try:
            nonce = w3.eth.get_transaction_count(account.address, 'pending')
            tx = {
                "to": contract_address,
                "from": account.address,
                "data": caldata,
                "nonce": nonce,
                "gas": get_gas_limit(caldata, value, contract_address),
                "gasPrice": get_gas_price(attempt),
                "value": value
            }
            signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = w3.to_hex(tx_hash)
            debug(f"Sniping attempt {attempt}/{max_attempts}, tx hash: {tx_hash_hex}")

            # Cek receipt menggunakan HTTP RPC
            for retry in range(3):
                try:
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                    if receipt.status == 1:
                        debug(f"Mint sukses, tx hash: {tx_hash_hex}")
                        print(f"Sniping berhasil! Hash: {tx_hash_hex}")
                        return True
                    else:
                        debug(f"Attempt {attempt} gagal di chain")
                        break
                except Exception:
                    debug(f"Gagal ambil receipt (retry {retry + 1}/3)")
                    time.sleep(1)
        except Exception as e:
            debug(f"Error attempt {attempt}: {str(e)}")
        time.sleep(0.05)
    
    print(f"Sniping gagal setelah {max_attempts} percobaan.")
    return False

# Fungsi untuk mengonversi harga ke wei berdasarkan input pengguna
def convert_to_wei(price_input):
    if not price_input or price_input.strip() == "":
        return w3.to_wei(0, "wei")  # Harga gratis (0 wei) jika Enter ditekan
    
    try:
        # Pisahkan input menjadi nilai dan unit (misalnya "0.1 ETH" atau "1000 GWEI")
        parts = price_input.strip().upper().split()
        value = float(parts[0])  # Ambil nilai numerik
        
        if len(parts) > 1:
            unit = parts[1]
            if unit == "ETH":
                return w3.to_wei(value, "ether")
            elif unit == "GWEI":
                return w3.to_wei(value, "gwei")
            elif unit == "WEI":
                return int(value)  # Pastikan integer untuk wei
            else:
                raise ValueError("Unit tidak valid! Gunakan ETH, GWEI, atau WEI.")
        else:
            # Jika tidak ada unit, anggap sebagai ETH
            return w3.to_wei(value, "ether")
        
    except ValueError as e:
        print(f"Error: Harga tidak valid! {str(e)}")
        return None

# Jalankan bot sniping dengan input harga yang lebih user-friendly
def run_sniping_bot():
    print("Bot Sniping NFT - Monad Testnet")
    contract_address = get_contract_address()
    
    # Minta input harga dengan opsi user-friendly
    price_input = input("Masukkan harga (contoh: '0.1 ETH', '1000 GWEI', atau '100000000000000000 WEI', tekan Enter untuk gratis): ").strip()
    value = convert_to_wei(price_input)
    
    if value is None:
        print("Sniping dibatalkan karena harga tidak valid.")
        return False
    
    print(f"Menggunakan harga {value} wei.")
    snipe_mint(contract_address, value)

# Start
if __name__ == "__main__":
    run_sniping_bot()
