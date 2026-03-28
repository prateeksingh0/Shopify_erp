from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken


def get_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access':  str(refresh.access_token),
    }


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()
        email    = request.data.get('email', '').strip()

        if not username or not password:
            return Response({'error': 'Username and password required'}, status=400)

        if User.objects.filter(username=username).exists():
            return Response({'error': 'Username already taken'}, status=400)

        user = User.objects.create_user(username=username, password=password, email=email)
        return Response(get_tokens(user), status=201)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()

        if not username or not password:
            return Response({'error': 'Username and password required'}, status=400)

        user = authenticate(username=username, password=password)
        if not user:
            return Response({'error': 'Invalid credentials'}, status=401)

        return Response(get_tokens(user))


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            'id':       request.user.id,
            'username': request.user.username,
            'email':    request.user.email,
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data.get('refresh'))
            token.blacklist()
        except Exception:
            pass
        return Response({'message': 'Logged out'})
    

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current  = request.data.get('current_password', '')
        new_pw   = request.data.get('new_password', '')

        if not current or not new_pw:
            return Response({'error': 'Both fields required'}, status=400)

        if not request.user.check_password(current):
            return Response({'error': 'Current password is incorrect'}, status=400)

        if len(new_pw) < 6:
            return Response({'error': 'Password must be at least 6 characters'}, status=400)

        request.user.set_password(new_pw)
        request.user.save()
        return Response({'message': 'Password changed successfully'})