"""Run explicitly: python manage.py test verification.test_browser --verbosity 2."""
from pathlib import Path
import os

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.test import override_settings
from playwright.sync_api import sync_playwright

from logistics.models import Department, Driver, Order, OrderItem, Payment, Product, Store, UserProfile, Vehicle
from logistics.application.services import TripPlanner, TripLifecycleService


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
        self.store = Store.objects.create(name="Cliente base", department=self.department, latitude="14.634915", longitude="-90.506882")
        order = Order.objects.create(origin=self.department, destination=self.department, store=self.store, weight_kg=20)
        OrderItem.objects.create(order=order, product=self.product, quantity=1, unit_price=20)
        vehicle = Vehicle.objects.create(plate="BROWSER", model="Reparto", capacity_kg=1000, fuel_efficiency_km_l=10, cost_per_km=2)
        self.trip = TripPlanner.plan_trip(vehicle, Order.objects.filter(pk=order.pk))
        self.trip = TripLifecycleService.start_trip(self.trip, recorded_by=self.user)
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
            self.page.evaluate("async () => { for (let i=0;i<150;i++) { if (await caches.open('flamia-shell-v8').then(cache => cache.match('/'))) return; await new Promise(r => setTimeout(r,100)); } throw new Error('Offline shell not ready'); }")
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

    def test_driver_arrival_dialog_confirms_delivery_inside_geofence(self):
        driver = Driver.objects.create(user=self.user, name="Repartidor GPS", license_number="WEB-GPS")
        self.trip.driver = driver
        self.trip.save(update_fields=["driver"])
        self.user.profile.role = UserProfile.Role.DRIVER
        self.user.profile.save(update_fields=["role"])
        stop = self.trip.stops.get()
        self.page.evaluate("reloadAll()")
        self.page.evaluate("""ids => {
            const trip = state.trips.find(row => row.id === ids.tripId);
            const stop = trip.stops.find(row => row.id === ids.stopId);
            const point = {lat: Number(stop.latitude), lng: Number(stop.longitude)};
            window.google = {maps: {SymbolPath: {FORWARD_CLOSED_ARROW: "arrow"}}};
            nav = {
                trip, stops: [stop], stepIndex: 0, position: null, heading: null, following: false,
                steps: [{path: [point, point], distance: 1, duration: 1, isLegEnd: true, legIndex: 0,
                         text: {main: "Llegada", detail: ""}, maneuver: "straight"}],
                driverMarker: {setPosition() {}, setIcon() {}},
                accuracyCircle: {setCenter() {}, setRadius() {}},
                arrivals: new Set(), offRouteCount: 0, announcedStep: -1, nearAnnounced: false, voice: false
            };
            onNavPosition(point, null, 10);
        }""", {"tripId": self.trip.pk, "stopId": stop.pk})
        dialog = self.page.locator("#arrival-dialog")
        dialog.wait_for(state="visible")
        self.assertIn("Llegaste a", dialog.inner_text())
        self.page.locator("#btn-confirm-arrival").click()
        self.page.wait_for_function("state.trips.some(trip => trip.stops.some(stop => stop.status === 'delivered'))")
        stop.refresh_from_db()
        self.assertEqual(stop.status, "delivered")
        self.assertEqual(stop.delivery_accuracy_m, 10)

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

    def test_credit_history_and_offline_partial_collection(self):
        order = self.trip.orders.get()
        self.tab("payments")
        self.page.locator("#payment-store").select_option(str(self.store.pk))
        self.page.locator("#payment-order").select_option(str(order.pk))
        self.page.locator('#payment-form [name="payment_type"]').select_option("credit")
        self.assertEqual(self.page.locator('#payment-form [name="amount"]').input_value(), "0.00")
        self.page.locator('#payment-form [type="submit"]').click()
        self.page.wait_for_function("state.payments.some(payment => payment.payment_type === 'credit') && !document.querySelector('[data-saving]')")
        self.assertEqual(order.balance_due, 20)
        self.context.set_offline(True)
        self.page.locator("#payment-store").select_option(str(self.store.pk))
        self.page.locator("#payment-order").select_option(str(order.pk))
        self.page.locator('#payment-form [name="amount"]').fill("7")
        self.page.locator('#payment-form [type="submit"]').click()
        self.queue_count(1)
        self.tab("stores")
        self.page.locator("#customer-history-select").select_option(str(self.store.pk))
        self.page.wait_for_function("document.querySelector('#customer-history').textContent.includes('Q 13.00')")
        self.assertIn("Abonado", self.page.locator("#customer-history").inner_text())
        self.assertIn("reparto", self.page.locator("#customer-history").inner_text())
        self.page.reload()
        self.page.wait_for_function("state.currentUser !== null")
        self.context.set_offline(False)
        self.page.evaluate("syncPendingData()")
        self.queue_count(0)
        self.assertEqual(order.balance_due, 13)
        self.assertEqual(Payment.objects.count(), 2)
        self.page.wait_for_function("state.report.paid_total === 7")

    def test_admin_can_update_role_from_users_module(self):
        self.user.profile.role = "admin"
        self.user.profile.save()
        other = User.objects.create_user("usuario-nuevo")
        UserProfile.objects.create(user=other, role="seller")
        self.page.evaluate("reloadAll()")
        self.tab("users")
        self.page.locator("#access-user").select_option(str(other.pk))
        self.page.locator('#user-access-form [name="role"]').select_option("supervisor")
        self.page.locator('#user-access-form [type="submit"]').click()
        self.page.wait_for_function("state.users.some(user => user.username === 'usuario-nuevo' && user.role === 'supervisor')")
        other.profile.refresh_from_db()
        self.assertEqual(other.profile.role, "supervisor")

    def test_admin_can_approve_pending_driver_from_dashboard(self):
        self.user.profile.role = "admin"
        self.user.profile.save()
        pending = User.objects.create_user("repartidor-pendiente", is_active=False)
        UserProfile.objects.create(user=pending, role="driver")
        driver = Driver.objects.create(user=pending, name="Repartidor Pendiente", license_number="PEND-01", is_active=False)
        self.page.evaluate("reloadAll()")
        card = self.page.locator("#pending-accounts-card")
        card.wait_for(state="visible")
        self.assertIn("repartidor-pendiente", card.inner_text())
        card.locator(f'[data-approve-user="{pending.pk}"]').click()
        self.page.wait_for_function("!state.users.some(user => user.username === 'repartidor-pendiente' && !user.is_active)")
        pending.refresh_from_db()
        driver.refresh_from_db()
        self.assertTrue(pending.is_active)
        self.assertTrue(driver.is_active)

    def test_new_offline_order_can_be_cancelled_before_synchronization(self):
        self.context.set_offline(True)
        self.page.evaluate("""async payload => {
            await postJsonOrQueue('/api/orders/', payload, 'Pedido de cliente');
            const order = state.orders.find(order => order.id < 0);
            await postJsonOrQueue(`/api/orders/${order.id}/action/`, {action:'cancel'}, 'Cancelar pedido');
        }""", {"origin_id": self.department.pk, "store_id": self.store.pk, "items": [{"product_id": self.product.pk, "quantity": 1}]})
        self.queue_count(2)
        self.assertEqual(self.page.evaluate("state.orders.find(order => order.id < 0).status"), "canceled")
        self.context.set_offline(False)
        self.page.evaluate("syncPendingData()")
        self.queue_count(0)
        self.assertEqual(Order.objects.filter(status="canceled").count(), 1)

    def test_offline_money_uses_cents_without_residual_balances(self):
        self.context.set_offline(True)
        result = self.page.evaluate("""async payload => {
            await postJsonOrQueue('/api/orders/', payload, 'Pedido con centavos');
            const order = state.orders.find(order => order.id < 0);
            await postJsonOrQueue('/api/payments/', {store_id:payload.store_id,order_id:order.id,
                amount:0.30,payment_type:'full_payment',uuid:makeLocalId()}, 'Pago con centavos');
            return state.orders.find(order => order.id < 0);
        }""", {"origin_id": self.department.pk, "store_id": self.store.pk,
                    "items": [{"product_id": self.product.pk, "quantity": 3, "unit_price": 0.10}]})
        self.assertEqual(result["total_amount"], 0.30)
        self.assertEqual(result["paid_amount"], 0.30)
        self.assertEqual(result["balance_due"], 0)
        self.assertEqual(result["payment_status"], "paid")
        self.context.set_offline(False)
        self.page.evaluate("syncPendingData()")
        self.queue_count(0)
        order = Order.objects.exclude(pk=self.trip.orders.get().pk).get()
        self.assertEqual(order.balance_due, 0)

    def test_supervisor_deletes_store_without_history(self):
        unused = Store.objects.create(name="Tienda para borrar", department=self.department, latitude="14.63", longitude="-90.51")
        self.page.evaluate("reloadAll()")
        self.tab("stores")
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.page.locator(f'[data-delete-kind="stores"][data-delete-id="{unused.pk}"]').click()
        self.page.wait_for_function("!state.stores.some(store => store.name === 'Tienda para borrar')")
        self.assertFalse(Store.objects.filter(pk=unused.pk).exists())
        self.assertTrue(Store.objects.filter(pk=self.store.pk).exists())

    def test_navigation_follows_steps_and_sanitizes_instructions(self):
        result = self.page.evaluate("""() => {
            const a = {lat: 14.6, lng: -90.5}, b = {lat: 14.6, lng: -90.497}, c = {lat: 14.603, lng: -90.497};
            const steps = [{path: [a, b]}, {path: [b, c]}];
            const html = 'Gira a la <b>derecha</b> hacia <b>5a Avenida</b><div>Destino a la izquierda</div><img src=x onerror="window.hacked=1">';
            return {
                middle: navLocate(steps, 0, {lat: 14.6001, lng: -90.4985}),
                corner: navLocate(steps, 0, b).index,
                away: navLocate(steps, 0, {lat: 14.61, lng: -90.4985}).offRoute,
                back: navLocate(steps, 1, a),
                text: navInstructionText(html),
                near: navFormatDistance(234), far: navFormatDistance(1530)
            };
        }""")
        self.assertEqual(result["middle"]["index"], 0)
        self.assertLess(result["middle"]["distance"], 15)
        self.assertTrue(150 < result["middle"]["remaining"] < 175)
        self.assertEqual(result["corner"], 1)
        self.assertTrue(result["away"])
        self.assertEqual(result["back"]["index"], 1)
        self.assertTrue(result["back"]["offRoute"])
        self.assertEqual(result["text"], {"main": "Gira a la derecha hacia 5a Avenida", "detail": "Destino a la izquierda"})
        self.assertFalse(self.page.evaluate("window.hacked === 1"))
        self.assertEqual((result["near"], result["far"]), ("230 m", "1.5 km"))
        self.tab("map")
        self.page.locator("#btn-start-nav").click()
        self.page.wait_for_function("document.getElementById('toast').textContent.includes('necesita conexion')")
        self.assertFalse(self.page.evaluate("document.body.classList.contains('is-navigating')"))

    def test_order_records_departure_gps(self):
        self.tab("orders")
        self.page.locator("#order-store").select_option(str(self.store.pk))
        self.page.locator("#order-origin").select_option(str(self.department.pk))
        self.page.locator("#order-product").select_option(str(self.product.pk))
        self.page.locator("#btn-order-departure-gps").click()
        self.page.wait_for_function("document.querySelector('#order-departure-status').textContent.includes('10 m')")
        self.page.locator('#order-form [type="submit"]').click()
        self.page.wait_for_function("document.getElementById('orders-body').textContent.includes('GPS ±10 m')")
        order = Order.objects.exclude(departure_latitude=None).get()
        self.assertEqual(str(order.departure_latitude), "14.634915")
        self.assertEqual(order.departure_accuracy_m, 10)


class WebKitOfflineTests(OfflineBrowserTests):
    engine = "webkit"
