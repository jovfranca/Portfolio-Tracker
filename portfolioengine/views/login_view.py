# Create your views here.
from django.shortcuts import render, redirect
from django.template import loader
from django.http import HttpResponse
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth import logout
from django.contrib import messages
from django.core.exceptions import ValidationError

def login_view(request):
    for message in messages.get_messages(request):
        # This will remove the message from the storage
        pass

    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_active:
                auth_login(request, user)
                return redirect('dashboard')
            else:
                messages.error(request, 'Your account is disabled')
        else:
            messages.error(request, 'Invalid login credentials')
    return render(request, "portfolioengine/login.html")