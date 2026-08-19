// Configuracao do frontend hospedado.
//
// Detecta automaticamente local vs. hospedado pelo hostname, para o mesmo
// arquivo servir os dois casos sem precisar editar nada ao alternar entre
// rodar no seu PC (Origin() vazio -- mesmo servidor) e o deploy na Vercel
// (Origin() aponta pro backend sempre-ligado no Render, ver DEPLOY.md).
(function () {
  var host = window.location.hostname;
  var local = host === "localhost" || host === "127.0.0.1" || host === "";
  window.API_BASE_URL = local ? "" : "https://radar-credito-backend.onrender.com";
})();
