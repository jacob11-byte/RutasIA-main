from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from logistics.models import Driver, UserProfile


class EmployeeSignupForm(UserCreationForm):
    role = forms.ChoiceField(
        label="Trabajo que realizara",
        choices=(
            (UserProfile.Role.SELLER, "Tomar pedidos y cobros en tiendas"),
            (UserProfile.Role.DRIVER, "Repartir pedidos y seguir rutas"),
        ),
    )
    first_name = forms.CharField(label="Nombres", max_length=150)
    last_name = forms.CharField(label="Apellidos", max_length=150)
    email = forms.EmailField(label="Correo electronico")
    phone = forms.CharField(label="Telefono", max_length=20, required=False)
    license_number = forms.CharField(
        label="Licencia o identificacion del repartidor",
        max_length=30,
        required=False,
        help_text="Es obligatorio solamente para repartidores.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username", "first_name", "last_name", "email", "role",
            "phone", "license_number", "password1", "password2",
        )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("role") == UserProfile.Role.DRIVER and not cleaned.get("license_number", "").strip():
            self.add_error("license_number", "La licencia o identificacion es obligatoria para un repartidor.")
        return cleaned

    def clean_license_number(self):
        value = self.cleaned_data.get("license_number", "").strip()
        if value and Driver.objects.filter(license_number=value).exists():
            raise forms.ValidationError("Ya existe un repartidor con esta licencia o identificacion.")
        return value
