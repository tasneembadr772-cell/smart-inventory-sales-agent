from django.shortcuts import render


def home(request):
    """
    Renders the starter landing page verifying that Django, templates,
    and static files are functioning properly.
    """
    context = {
        'project_name': 'Inventory & Sales Management System',
        'status': 'Project Scaffold Initialized Successfully',
    }
    return render(request, 'core/index.html', context)
