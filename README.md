# 🏛 LicitaçõesPNCP — Versão Online

Sistema de busca de licitações públicas do PNCP, hospedado gratuitamente online.
Banco atualizado automaticamente a cada hora. Busca instantânea.

---

## 🚀 Como colocar no ar (passo a passo visual)

### ETAPA 1 — Criar conta no GitHub
1. Acesse **github.com** e clique em "Sign up"
2. Use seu e-mail, crie uma senha, confirme o e-mail
3. Pronto — você tem uma conta no GitHub

---

### ETAPA 2 — Criar conta no Supabase (banco de dados gratuito)
1. Acesse **supabase.com** e clique em "Start your project"
2. Faça login com sua conta do GitHub
3. Clique em **"New Project"**
4. Escolha um nome (ex: `licitacoes-pncp`)
5. Crie uma senha forte (anote ela!)
6. Selecione região: **South America (São Paulo)**
7. Clique em **"Create new project"** — aguarde ~2 minutos
8. Vá em **Project Settings → Database**
9. Copie a **"Connection String"** (URI) — parece assim:
   ```
   postgresql://postgres:SUA_SENHA@db.XXXXX.supabase.co:5432/postgres
   ```
10. **Guarde essa string** — vai precisar no próximo passo

---

### ETAPA 3 — Subir o código no GitHub
1. Em **github.com**, clique em **"+"** → **"New repository"**
2. Nome: `licitacoes-pncp`
3. Deixe como **Private** (privado)
4. Clique em **"Create repository"**
5. Na próxima tela, clique em **"uploading an existing file"**
6. **Arraste todos os arquivos** desta pasta para a janela do navegador
7. Clique em **"Commit changes"**

---

### ETAPA 4 — Criar conta no Railway (hospedagem gratuita)
1. Acesse **railway.app** e clique em "Start a New Project"
2. Faça login com sua conta do GitHub (autorize o acesso)
3. Clique em **"Deploy from GitHub repo"**
4. Selecione o repositório `licitacoes-pncp`
5. Railway vai detectar o projeto Python automaticamente

---

### ETAPA 5 — Configurar a variável do banco de dados
1. No painel do Railway, clique no seu projeto
2. Vá em **"Variables"** (variáveis de ambiente)
3. Clique em **"New Variable"**
4. Nome: `DATABASE_URL`
5. Valor: cole a Connection String do Supabase (passo 2, item 9)
6. Clique em **"Add"**

---

### ETAPA 6 — Gerar o link público
1. No Railway, vá em **"Settings"** do seu serviço
2. Em **"Networking"**, clique em **"Generate Domain"**
3. Vai aparecer um link tipo: `licitacoes-pncp-production.up.railway.app`
4. **Esse é o seu link!** Acesse pelo navegador, celular, qualquer lugar.

---

## ✅ Pronto! O que acontece automaticamente

- Ao iniciar, o sistema baixa os últimos 30 dias do PNCP
- **A cada hora**, busca novas licitações automaticamente
- **Toda segunda-feira às 3h**, faz uma varredura completa dos últimos 7 dias
- Você só precisa acessar o link e buscar — sem clicar em "atualizar"

---

## 💡 Como usar

1. Acesse seu link do Railway
2. Digite uma palavra-chave (ex: `medicamentos`, `obras`, `limpeza`)
3. Selecione filtros: UF, Modalidade, Valor, Data
4. Clique em **🔍 Buscar** — resultado instantâneo
5. ⭐ para favoritar licitações interessantes
6. **📥 Exportar Excel** para baixar os resultados

---

## 🔧 Limites do plano gratuito

| Serviço | Limite gratuito |
|---------|----------------|
| Railway | 500 horas/mês (suficiente para rodar 24h) |
| Supabase | 500 MB de banco (cabem ~500.000 licitações) |
| Ambos | Sem necessidade de cartão de crédito |

---

## 🚀 Melhorias futuras (rumo ao SaaS pago)

- **Alertas por e-mail** — notificar quando aparecerem licitações com palavras-chave específicas
- **Multi-usuário** — cada cliente com seus próprios filtros e favoritos
- **Score de relevância por IA** — classificação automática por área de atuação
- **Integração WhatsApp** — receber alertas direto no celular
- **Painel administrativo** — estatísticas de uso, gestão de clientes
- **Cobrança por assinatura** — R$97-297/mês por empresa de assessoria
