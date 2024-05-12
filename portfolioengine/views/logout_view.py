from django.shortcuts import render, redirect
from django.template import loader
from django.http import HttpResponse
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth import logout
from django.contrib import messages
from django.core.exceptions import ValidationError

def logout_view(request):
    logout(request)
    return redirect('index')