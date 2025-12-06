// Funções para validação de formulários e interações
document.addEventListener('DOMContentLoaded', function() {

    // Função para formatar número com zeros à esquerda
    function padNumber(num, size) {
        let s = num + "";
        while (s.length < size) s = "0" + s;
        return s;
    }

    // Função para formatar valor como moeda (R$ 0.000,00)
    function formatCurrency(input) {
        let value = input.value.replace(/\D/g, ''); // Remove tudo que não for dígito
        value = (parseInt(value) / 100).toFixed(2) + ''; // Converte para número, divide por 100 e fixa 2 casas decimais
        value = value.replace(".", ","); // Troca ponto por vírgula
        value = value.replace(/(\d)(?=(\d{3})+(?!\d))/g, '$1.'); // Adiciona ponto como separador de milhar
        input.value = 'R$ ' + value;
        if (input.value === 'R$ NaN' || input.value === 'R$ 0,00') {
            input.value = ''; // Limpa se for inválido ou zero inicial
        }
    }

    // Máscara para campo de telefone
    const telefoneInput = document.getElementById('contato');
    if (telefoneInput) {
        telefoneInput.addEventListener('input', function(e) {
            let value = e.target.value.replace(/\D/g, '');
            if (value.length > 0) {
                // Formata como (XX) XXXXX-XXXX ou (XX) XXXX-XXXX
                if (value.length <= 2) {
                    value = `(${value}`;
                } else if (value.length <= 6) {
                    value = `(${value.substring(0, 2)}) ${value.substring(2)}`; // (XX) XXXX
                } else if (value.length <= 10) {
                     value = `(${value.substring(0, 2)}) ${value.substring(2, 6)}-${value.substring(6)}`; // (XX) XXXX-XXXX
                } else {
                    value = `(${value.substring(0, 2)}) ${value.substring(2, 7)}-${value.substring(7, 11)}`; // (XX) XXXXX-XXXX
                }
                e.target.value = value;
            }
        });
    }

    // Validação de formulário de cadastro de usuário
    const formUsuario = document.querySelector('form[action*="usuario"]');
    if (formUsuario) {
        formUsuario.addEventListener('submit', function(e) {
            const senhaInput = document.getElementById('senha');
            const confirmarSenhaInput = document.getElementById('confirmar_senha');
            
            if (senhaInput && confirmarSenhaInput) {
                const senha = senhaInput.value;
                const confirmarSenha = confirmarSenhaInput.value;
                if (senha !== confirmarSenha) {
                    e.preventDefault();
                    alert('As senhas não coincidem!');
                }
            }
        });
    }

    // Confirmação para devolução de empréstimo
    const devolverLinks = document.querySelectorAll('a[href*="devolver_emprestimo"]');
    devolverLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            if (!confirm('Confirma a devolução deste item?')) {
                e.preventDefault();
            }
        });
    });

    // Auto-fechar alertas após 5 segundos
    const alertas = document.querySelectorAll('.alert');
    alertas.forEach(alerta => {
        setTimeout(() => {
            alerta.classList.add('fade');
            setTimeout(() => {
                alerta.remove();
            }, 500);
        }, 5000);
    });

    // Formatação de tombamento (4 dígitos com zeros à esquerda)
    const tombamentoInput = document.getElementById('tombamento');
    if (tombamentoInput) {
        tombamentoInput.addEventListener('blur', function(e) {
            let value = e.target.value.trim().replace(/\D/g, ''); // Remove não dígitos
            if (value) { // Só formata se houver valor
                 e.target.value = padNumber(value, 4);
            }
        });
    }

    // Formatação de valor (R$ 00,00)
    const valorInput = document.getElementById('valor');
    if (valorInput) {
        valorInput.addEventListener('input', function(e) {
            formatCurrency(e.target);
        });
        // Formata ao carregar a página caso já exista valor (edição)
        if(valorInput.value) {
             formatCurrency(valorInput);
        }
    }
});
