// Configuracao do frontend hospedado.
//
// URL relativa (mesma origem) SEMPRE -- tanto local quanto hospedado. Local: o
// proprio `uvicorn webapp.main:app` serve front+back no mesmo processo (mount de
// StaticFiles em webapp/main.py). Hospedado: a API e o site estatico agora moram
// no MESMO dominio da Vercel (vercel.json roteia /api/* para a funcao Python,
// tudo o mais vem de webapp/static/ pela CDN) -- ver DEPLOY.md. Antes deste
// arquivo apontava para um backend num dominio separado (Render); com os dois
// lados no mesmo dominio no ar, esse desvio deixou de existir.
window.API_BASE_URL = "";
