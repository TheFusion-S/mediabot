# ☁️ MediaBot'ni serverga o'rnatish (kun-u tun ishlaydi)

Bot serverda ishlasa, kompyuteringiz o'chiq bo'lsa ham ishlayveradi. Kerak bo'ladi:
- **Server**: bepul **Oracle Cloud** (pastda) yoki pullik VPS (oyiga ~4–6 $). Ubuntu **24.04**, kamida 1 GB RAM.
- Bot tokeni (@BotFather).
- Mac'da **Terminal** — faqat bir marta, fayllarni serverga yuborish uchun.

## 🆓 Bepul variant: Oracle Cloud "Always Free"

Oracle doimiy bepul server beradi (Ampere ARM: 4 tagacha yadro / 24 GB RAM). Ro'yxatdan o'tishda bank kartasi
**faqat tekshirish uchun** so'raladi — bepul resurslar uchun pul yechilmaydi (shartlarni ro'yxatdan o'tishda
o'zingiz ham o'qib chiqing, ular o'zgarishi mumkin).

**1. Ro'yxatdan o'ting:** https://www.oracle.com/cloud/free/ → *Start for free*.
   *Home Region* sifatida yaqinroq shaharni tanlang (masalan Frankfurt) — keyin o'zgartirib bo'lmaydi.

**2. Server yarating:** Menyu → *Compute* → *Instances* → *Create instance*:
   - *Image*: **Canonical Ubuntu 24.04**
   - *Shape*: **Ampere → VM.Standard.A1.Flex**, 1–2 OCPU, 6–12 GB RAM (*Always Free-eligible* yozuvi bo'lsin).
     "Out of capacity" desa — boshqa *Availability domain*ni tanlang yoki **VM.Standard.E2.1.Micro** ni oling.
   - *Networking*: standart VCN, **Assign a public IPv4 address** yoqilgan bo'lsin.
   - *Add SSH keys*: **Generate a key pair for me** → **Save private key** (fayl Downloads'ga tushadi,
     nomi `ssh-key-....key` — uni yo'qotmang!).
   - *Create* ni bosing. Bir necha daqiqadan keyin *Public IP address* chiqadi — yozib oling.

**3. 80 va 443 portlarini oching** (Mini App HTTPS uchun):
   Instance sahifasi → *Subnet* havolasi → *Security Lists* → *Default Security List* → *Add Ingress Rules*:
   - *Source CIDR*: `0.0.0.0/0`, *IP Protocol*: TCP, *Destination Port Range*: `80,443` → *Add*.

**4. Mac Terminal'dan bitta buyruq** (`IP` o'rniga serveringiz IP'sini 2 joyda yozing).
   `MediaBot-tayyor.zip` va `ssh-key-....key` ikkalasi ham Downloads'da bo'lsin:

```
chmod 600 ~/Downloads/ssh-key-*.key && scp -i ~/Downloads/ssh-key-*.key ~/Downloads/MediaBot-tayyor.zip ubuntu@IP:~ && ssh -t -i ~/Downloads/ssh-key-*.key ubuntu@IP "sudo apt-get update -qq && sudo apt-get install -y -qq unzip && unzip -oq MediaBot-tayyor.zip && sudo bash MediaBot/scripts/install-server.sh"
```

   `Are you sure you want to continue connecting` → `yes`. Parol so'ralmaydi (kalit ishlatiladi).
   Keyin skript tokenni so'raydi va botga /start yuborishingizni aytadi — tamom.
   Boshqarish uchun serverga kirish: `ssh -i ~/Downloads/ssh-key-*.key ubuntu@IP`, keyin `sudo mediabot status`.

---

## Pullik VPS (boshqa provayderlar)

## 1. Server sotib oling

Istalgan provayder bo'ladi: Hetzner, DigitalOcean, Vultr, Contabo yoki O'zbekistondagi hosting.
Server yaratishda:
1. Tizim: **Ubuntu 24.04**
2. Kirish usuli: **Password** (parol) — provayder parolni email orqali yuboradi yoki o'zingiz kiritasiz.
3. Yaratilgach, serverning **IP manzilini** yozib oling (masalan `203.0.113.7`).

## 2. Bitta buyruq bilan o'rnatish (Mac Terminal'dan)

`MediaBot-tayyor.zip` **Downloads** papkasida bo'lsin. Terminal'ni oching (Cmd + Probel → `Terminal`) va
quyidagida `IP` o'rniga serveringiz IP manzilini yozib, Enter bosing:

```
scp ~/Downloads/MediaBot-tayyor.zip root@IP:/root/ && ssh -t root@IP "apt-get update -qq && apt-get install -y -qq unzip && unzip -oq MediaBot-tayyor.zip && bash MediaBot/scripts/install-server.sh"
```

- Birinchi marta `Are you sure you want to continue connecting` deb so'rasa — `yes` yozing.
- Server **paroli** ikki marta so'raladi (yozganda ko'rinmaydi — bu normal).
- Keyin skript **bot tokenini** so'raydi (Cmd+V, ko'rinmaydi) va botga **/start** yuborishingizni aytadi.

Qolganini skript o'zi qiladi: dasturlar, sizni bot egasi qilish (/mode bilan ochiq yoki yopiq), Mini App uchun HTTPS
(`https://<IP>.sslip.io` — domen sotib olish shart emas), server qayta yoqilganda avtomatik ishga tushish.
Oxirida **✅ Tayyor!** chiqadi. Endi Mac'ni o'chirsangiz ham bot ishlaydi.

## 3. Boshqarish

Serverga kirish: `ssh root@IP`, keyin:

| Buyruq | Nima qiladi |
|---|---|
| `mediabot status` | holati va so'nggi loglar |
| `mediabot logs` | jonli loglar (chiqish: Ctrl+C) |
| `mediabot restart` | qayta ishga tushirish |
| `mediabot update` | yt-dlp'ni yangilash (YouTube/Instagram ishlamay qolsa) |

Yangi versiyani o'rnatish — 2-bo'limdagi buyruqni qayta ishga tushiring (token va sozlamalar saqlanadi).

## ⚠️ Muhim: YouTube va Instagram serverlarni bloklashi mumkin

YouTube va Instagram ma'lumotlar markazlari (VPS) IP manzillaridan kelgan so'rovlarni ko'pincha
"bot emasligingizni tasdiqlang" deb to'sib qo'yadi. Bunday bo'lsa bot sizga shu haqda aniq xabar beradi.
Yechim — **cookies** fayli:

1. Kompyuteringizdagi brauzerga "Get cookies.txt LOCALLY" kengaytmasini o'rnating.
2. YouTube'ga (va kerak bo'lsa Instagram'ga) kirgan holda cookies'ni eksport qiling va fayl nomini
   `cookies.txt` qiling. Asosiy emas, **qo'shimcha akkaunt** ishlatish tavsiya etiladi.
3. Faylni `~/Downloads/MediaBot/` ichiga qo'ying va 2-bo'limdagi buyruqni o'rniga quyidagini ishga tushiring:

```
scp ~/Downloads/MediaBot/cookies.txt root@IP:/root/MediaBot/cookies.txt && ssh -t root@IP "bash MediaBot/scripts/install-server.sh"
```

Cookies vaqt o'tib eskiradi — bot yana bloklansa, shu qadamni takrorlang.
