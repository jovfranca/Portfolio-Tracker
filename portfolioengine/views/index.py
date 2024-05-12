from django.shortcuts import render

def index(request):
    context = {"user": request.user}
    return render(request, "portfolioengine/index.html", context)