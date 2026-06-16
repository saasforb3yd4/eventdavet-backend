// cloudflare-worker-example.js
// Amaç:
// eventdavet.com/ayse-mert/ ve eventdavet.com/ayse-mert/katilimcilar gibi yolları
// Python/Flask davetiye sunucuna yönlendirmek.
// Diğer Shopify sayfalarını Shopify'da bırakmak.
//
// BACKEND_ORIGIN değerini kendi Python sunucunla değiştir.
// Örnek: https://backend.eventdavet.com

const BACKEND_ORIGIN = "https://backend.eventdavet.com";

// Shopify'ın normal yolları. Bunları backend'e gönderme.
const RESERVED_FIRST_SEGMENTS = new Set([
  "admin", "cart", "checkout", "collections", "products", "pages", "blogs",
  "account", "search", "policies", "cdn", "apps", "tools", "a",
  "community", "sitemap.xml", "robots.txt"
]);

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);
    const first = parts[0] || "";

    // Ana sayfa ve Shopify standart yolları Shopify'da kalsın.
    if (!first || RESERVED_FIRST_SEGMENTS.has(first)) {
      return fetch(request);
    }

    // Davetiye slug mantığı:
    // /ayse-mert/
    // /ayse-mert/katilimcilar
    // /ayse-mert/api/katilim
    // /ayse-mert/assets/...
    const backendUrl = new URL(request.url);
    const backendOrigin = new URL(BACKEND_ORIGIN);
    backendUrl.protocol = backendOrigin.protocol;
    backendUrl.hostname = backendOrigin.hostname;
    backendUrl.port = backendOrigin.port;

    const proxiedRequest = new Request(backendUrl.toString(), request);
    return fetch(proxiedRequest);
  }
};
