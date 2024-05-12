from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

def signup_view(request):
    for message in messages.get_messages(request):
        # This will remove the message from the storage
        pass

    if request.method == "POST":
        username = request.POST['username']
        email = request.POST['email']
        password1 = request.POST['password1']
        password2 = request.POST['password2']

        if password1 != password2:
            messages.error(request, "Passwords don't match")
            return render(request, 'portfolioengine/signup.html')
        else:
            try:
                user = User.objects.create_user(username, email, password1)
                user.full_clean()
                auth_login(request, user)
                messages.success(request, 'Your account has been created!')
                return redirect('dashboard')
            except ValidationError as e:
                messages.error(request, e.messages[0])
                return render(request, 'portfolioengine/signup.html')
            
    return render(request, 'portfolioengine/signup.html')