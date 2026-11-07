"""Run explicitly: python manage.py test verification.test_browser --verbosity 2."""
from pathlib import Path
import os

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.test import override_settings
from playwright.sync_api import sync_playwright

from logistics.models import Department, Order, Payment, Product, Store, UserProfile, Vehicle
from logistics.application.services import TripPlanner


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class OfflineBrowserTests(StaticLiveServerTestCase):
    engine = "chromium"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Playwright's sync driver keeps an event loop on this thread. ORM calls
        # below are sequential, while HTTP requests run on Django's server thread.
        cls.previous_async_setting = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        cls.playwright = sync_playwright().start()
        if cls.engine == "chromium":
            chrome = Path(os.environ.get("FLAMIA_CHROME_EXECUTABLE", "C:/Program Files/Google/Chrome/Application/chrome.exe"))
            cls.browser = cls.playwright.chromium.launch(**({"executable_path": str(chrome)} if chrome.exists() else {}), headless=True)
        else:
            cls.browser = cls.playwright.webkit.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        if cls.previous_async_setting is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = cls.previous_async_setting
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("reparto", password="test-password")
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.SUPERVISOR)
        self.department = Department.objects.create(code="GUA", name="Guatemala", latitude="14.63", longitude="-90.51")
        self.product = Product.objects.create(name="Agua", unit_price=20, unit_weight_kg=20)
        self.store = Store.objects.create(name="Cliente base", department=self.department, latitude="14.63", longitude="-90.51")
        order = Order.objects.create(origin=self.department, destination=self.department, store=self.store, weight_kg=20)
        vehicle = Vehicle.objects.create(plate="BROWSER", model="Reparto", capacity_kg=1000, fuel_efficiency_km_l=10, cost_per_km=2)
        self.trip = TripPlanner.plan_trip(vehicle, Order.objects.filter(pk=order.pk))
        options = {"viewport": {"width": 390, "height": 844}, "geolocation": {"latitude": 14.634915, "longitude": -90.506882, "accuracy": 10}, "permissions": ["geolocation"]}
        if self.engine == "webkit":
            options.update(is_mobile=True, has_touch=True)
        self.context = self.browser.new_context(**options)
        # No external map calls, paid keys, or route geometry are needed for these tests.
        self.context.route("**/maps.googleapis.com/**", lambda route: route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.live_server_url + "/accounts/login/")
        self.page.locator('[name="username"]').fill("reparto")
        self.page.locator('[name="password"]').fill("test-password")
        self.page.locator('button[type="submit"]').click()
        try:
            self.page.wait_for_function("typeof state !== 'undefined' && state.currentUser !== null", timeout=15000)
            self.page.wait_for_function("!!navigator.serviceWorker.controller", timeout=15000)
            self.page.evaluate("async () => { for (let i=0;i<150;i++) { if (await caches.open('flamia-shell-v3').then(cache => cache.match('/'))) return; await new Promise(r => setTimeout(r,100)); } throw new Error('Offline shell not ready'); }")
        except Exception:
            print("Browser diagnostic:", self.page.url, self.errors, self.page.locator("body").inner_text()[-1000:], flush=True)
            raise
        self.page.wait_for_function("document.querySelector('#store-department').options.length > 0")

    def tearDown(self):
        # Drain application requests before Django flushes the test database.
        # Browser network-idle also counts worker traffic and is not reliable here.
        self.page.evaluate("clearInterval(offlineRetryTimer); reloadAll()")
        self.context.close()

    def tab(self, name):
        self.page.locator(f'.tab[data-tab="{name}"]').click()

    def queue_count(self, count):
        self.page.wait_for_function("count => offlinePendingCount === count && !isSyncingOfflineQueue", arg=count)
        self.page.wait_for_function("!document.querySelector('[data-saving]')")

    def test_offline_store_order_payment_reload_and_sync(self):
        self.context.set_offline(True)
        self.tab("stores")
        self.page.locator('#store-form [name="name"]').fill("Tienda sin red")
        self.page.locator('#store-form [name="municipality"]').fill("Guatemala")
        self.page.locator('#store-form [name="neighborhood"]').fill("Zona 7")
        self.page.locator("#store-department").select_option(str(self.department.pk))
        self.page.locator("#btn-store-gps").click()
        self.page.wait_for_function("document.querySelector('#store-gps-status').textContent.includes('10 m')")
        self.page.locator('#store-form [type="submit"]').click()
        self.queue_count(1)
        self.page.wait_for_function("state.stores.some(store => store.name === 'Tienda sin red')")
        store_id = self.page.evaluate("state.stores.find(store => store.name === 'Tienda sin red').id")
        self.assertLess(store_id, 0)
        self.tab("orders")
        self.page.locator("#order-store").select_option(str(store_id))
        self.page.locator("#order-origin").select_option(str(self.department.pk))
        self.page.locator("#order-product").select_option(str(self.product.pk))
        self.page.locator('#order-form [name="quantity"]').fill("2")
        self.page.locator('#order-form [type="submit"]').click()
        self.queue_count(2)
        self.page.wait_for_function("state.orders.some(order => order.store_id < 0)")
        order_id = self.page.evaluate("state.orders.find(order => order.store_id < 0).id")
        self.tab("payments")
        self.page.locator("#payment-store").select_option(str(store_id))
        self.page.locator("#payment-order").select_option(str(order_id))
        self.page.locator('#payment-form [name="amount"]').fill("15")
        self.page.locator('#payment-form [type="submit"]').click()
        self.queue_count(3)
        self.page.reload()
        self.page.wait_for_function("typeof state !== 'undefined' && state.orders.some(order => order.store_id < 0)")
        self.assertEqual(self.page.evaluate("state.orders.find(order => order.store_id < 0).balance_due"), 25)
        self.assertEqual(self.page.evaluate("state.balances.find(row => row.store_id < 0).balance_due"), 25)
        self.context.set_offline(False)
        self.page.evaluate("syncPendingData()")
        self.queue_count(0)
        store = Store.objects.get(name="Tienda sin red")
        self.assertEqual(store.location_accuracy_m, 10)
        order = Order.objects.get(store=store)
        self.assertEqual(order.total_amount, 40)
        self.assertEqual(order.balance_due, 25)
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)
        self.assertEqual(Payment.objects.get(order=order).sync_status, "synced")
        self.assertEqual(self.errors, [])

    def test_delivery_location_offline_and_permission_denied(self):
        self.context.set_offline(True)
        self.tab("trips")
        self.page.locator("#delivery-trip").select_option(str(self.trip.pk))
        stop = self.trip.stops.get()
        self.page.locator("#delivery-stop").select_option(str(stop.pk))
        self.page.locator("#btn-delivery-gps").click()
        self.page.wait_for_function("document.querySelector('#delivery-gps-status').textContent.includes('10 m')")
        self.page.locator('#delivery-location-form [type="submit"]').click()
        self.queue_count(1)
        self.page.wait_for_function("state.trips.some(trip => trip.stops.some(stop => stop.status === 'delivered' && stop.delivery_accuracy_m === 10))")
        self.context.set_offline(False)
        self.page.evaluate("syncPendingData()")
        self.queue_count(0)
        stop.refresh_from_db()
        self.assertEqual(float(stop.delivery_latitude), 14.634915)
        self.assertEqual(stop.delivery_accuracy_m, 10)
        self.assertEqual(stop.status, "delivered")
        self.page.evaluate("navigator.geolocation.getCurrentPosition = (ok, fail) => fail({code: 1}); navigator.geolocation.watchPosition = () => 1;")
        self.tab("stores")
        self.page.locator("#btn-store-gps").click()
        self.page.wait_for_function("document.querySelector('#store-gps-status').textContent.includes('Ubicacion bloqueada')")
        self.assertEqual(self.errors, [])

    def test_lost_response_replays_without_duplicate_and_storage_failure_is_visible(self):
        self.page.evaluate("window.setInterval = () => 0")
        # The server commits, then the network drops before the client receives it.
        self.page.evaluate("""() => {
            window.actualFetch = window.fetch;
            window.fetch = async (...args) => {
                const response = await window.actualFetch(...args);
                if (args[0] === '/api/stores/' && args[1]?.method === 'POST') throw new TypeError('Failed to fetch');
                return response;
            };
        }""")
        payload = {"name": "Respuesta perdida", "department_id": self.department.pk, "latitude": 14.63, "longitude": -90.51}
        self.page.evaluate("payload => postJsonOrQueue('/api/stores/', payload, 'Tienda respuesta perdida')", payload)
        self.assertEqual(Store.objects.filter(name="Respuesta perdida").count(), 1)
        self.queue_count(1)
        self.page.evaluate("window.fetch = window.actualFetch")
        self.page.evaluate("syncPendingData()")
        self.queue_count(0)
        self.assertEqual(Store.objects.filter(name="Respuesta perdida").count(), 1)
        result = self.page.evaluate("""async () => {
            FlamiaOffline.enqueue = async () => { throw new Error('Sin espacio disponible'); };
            try { await postJsonOrQueue('/api/stores/', {}, 'No guardado'); return 'incorrecto'; }
            catch (error) { return error.message; }
        }""")
        self.assertEqual(result, "Sin espacio disponible")

    def test_expired_session_preserves_pending_and_accounts_are_separate(self):
        self.context.set_offline(True)
        payload = {"name": "Pendiente privado", "department_id": self.department.pk, "latitude": 14.63, "longitude": -90.51}
        self.page.evaluate("payload => postJsonOrQueue('/api/stores/', payload, 'Tienda privada')", payload)
        self.queue_count(1)
        Session.objects.all().delete()
        self.context.set_offline(False)
        self.page.evaluate("syncPendingData()")
        self.queue_count(1)
        self.assertFalse(Store.objects.filter(name="Pendiente privado").exists())
        other = User.objects.create_user("otra-cuenta", password="test-password")
        UserProfile.objects.create(user=other, role=UserProfile.Role.SUPERVISOR)
        self.client.force_login(other)
        self.context.add_cookies([{"name": "sessionid", "value": self.client.cookies["sessionid"].value, "url": self.live_server_url}])
        # The old tab cannot send records using the newly logged-in account.
        self.page.evaluate("syncPendingData()")
        self.queue_count(1)
        self.assertFalse(Store.objects.filter(name="Pendiente privado").exists())
        self.page.reload()
        self.page.wait_for_function("state.currentUser !== null")
        self.assertEqual(self.page.evaluate("state.currentUser.username"), "otra-cuenta")
        self.assertEqual(self.page.evaluate("async () => (await FlamiaOffline.read()).queue.length"), 0)

    def test_concurrent_sync_with_safari_lock_fallback(self):
        self.context.set_offline(True)
        self.page.evaluate("""async department => {
            Object.defineProperty(navigator, 'locks', {value: undefined});
            for (const name of ['Pendiente A', 'Pendiente B']) await postJsonOrQueue('/api/stores/',
                {name,department_id:department,latitude:14.63,longitude:-90.51}, name);
        }""", self.department.pk)
        self.queue_count(2)
        self.context.set_offline(False)
        self.page.evaluate("Promise.all([syncPendingData(),syncPendingData()])")
        self.queue_count(0)
        self.assertEqual(Store.objects.filter(name__in=["Pendiente A", "Pendiente B"]).count(), 2)


class WebKitOfflineTests(OfflineBrowserTests):
    engine = "webkit"
