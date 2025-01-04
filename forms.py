from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, FileField, MultipleFileField
from wtforms.validators import DataRequired, Optional

class VeiculoForm(FlaskForm):
    marca = StringField('Marca', validators=[DataRequired()])
    modelo = StringField('Modelo', validators=[DataRequired()])
    cor = StringField('Cor', validators=[DataRequired()])
    placa = StringField('Placa', validators=[DataRequired()])

class ParenteForm(FlaskForm):
    nome = StringField('Nome', validators=[DataRequired()])
    mae = StringField('Nome da Mãe', validators=[Optional()])
    pai = StringField('Nome do Pai', validators=[Optional()])
    nascimento = DateField('Data de Nascimento', validators=[Optional()])
    rg = StringField('RG', validators=[Optional()])
    cpf = StringField('CPF', validators=[Optional()])
    endereco = StringField('Endereço', validators=[Optional()])
    foto_perfil = FileField('Foto de Perfil', validators=[Optional()])
    fotos = MultipleFileField('Fotos Adicionais', validators=[Optional()])
    anotacoes = TextAreaField('Anotações', validators=[Optional()])

class AbordadoForm(FlaskForm):
    nome = StringField('Nome', validators=[DataRequired()])
    mae = StringField('Nome da Mãe', validators=[Optional()])
    pai = StringField('Nome do Pai', validators=[Optional()])
    nascimento = StringField('Data de Nascimento', validators=[Optional()])
    rg = StringField('RG', validators=[Optional()])
    cpf = StringField('CPF', validators=[Optional()])
    endereco = StringField('Endereço', validators=[Optional()])
    telefone = StringField('Telefone', validators=[Optional()])
    foto_perfil = FileField('Foto de Perfil', validators=[Optional()])
    fotos = MultipleFileField('Fotos Adicionais', validators=[Optional()])
    anotacoes = TextAreaField('Anotações', validators=[Optional()])

class AbordagemForm(FlaskForm):
    data_hora = StringField('Data/Hora', validators=[DataRequired()])
    local = StringField('Local', validators=[DataRequired()])
    anotacao = TextAreaField('Anotação') 